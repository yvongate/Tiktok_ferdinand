import { Injectable, Logger, NotFoundException, OnModuleInit } from '@nestjs/common';
import { randomUUID } from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import { Subject } from 'rxjs';
import { diagnose } from './diagnose';
import type { Job, JobIncident, JobParams, JobProgress } from './job.types';
import { PythonRunnerService, type ParsedIncident } from './python-runner.service';

const MAX_LOG_LINES = 300;
/** Au-dela, on garde les plus recents (un job long peut en accumuler). */
const MAX_INCIDENTS = 100;

/**
 * Silence maximal tolere avant de signaler un blocage. Le script emet un
 * battement toutes les ~24s pendant les attentes longues, donc 3 minutes sans
 * la moindre ligne signifie que quelque chose ne repond plus.
 */
const STALL_MS = 3 * 60 * 1000;
const STALL_CHECK_MS = 30 * 1000;

/**
 * Registre des jobs + file d'attente SEQUENTIELLE (une generation a la fois -
 * les generations sont de toute facon limitees par les API externes, et faire
 * tourner plusieurs FFmpeg en parallele n'apporterait rien).
 *
 * Volontairement sans Redis/BullMQ : pour un usage mono-utilisateur, une file
 * en memoire persistee sur disque suffit et evite un service supplementaire a
 * heberger. Toute la logique de file est isolee ici : passer a BullMQ plus
 * tard ne toucherait que ce fichier.
 */
@Injectable()
export class JobsService implements OnModuleInit {
  private readonly logger = new Logger(JobsService.name);
  private readonly jobs = new Map<string, Job>();
  private readonly queue: string[] = [];
  private processing = false;
  private readonly running = new Map<string, { kill: () => void }>();
  /** Jobs dont l'annulation a ete demandee (plus fiable que de relire un
   *  champ mute pendant l'await de fin de process). */
  private readonly cancelRequested = new Set<string>();

  /** Flux d'evenements pour le SSE (un evenement par mise a jour de job). */
  readonly events = new Subject<Job>();

  constructor(private readonly runner: PythonRunnerService) {}

  private get dataDir(): string {
    return process.env.DATA_DIR ?? path.resolve(__dirname, '..', '..', 'data');
  }

  private get jobsFile(): string {
    return path.join(this.dataDir, 'jobs.json');
  }

  onModuleInit() {
    fs.mkdirSync(this.dataDir, { recursive: true });
    this.load();
  }

  // --- API publique ---------------------------------------------------

  create(params: JobParams): Job {
    const id = randomUUID();
    const job: Job = {
      id,
      params,
      status: 'queued',
      progress: { step: 'pending', percent: 0, message: "En attente d'un worker" },
      createdAt: new Date().toISOString(),
      outDir: path.join(this.dataDir, 'jobs', id),
      incidents: [],
      logTail: [],
    };
    fs.mkdirSync(job.outDir, { recursive: true });
    this.jobs.set(id, job);
    this.queue.push(id);
    this.touch(job);
    void this.drain();
    return job;
  }

  list(): Job[] {
    return [...this.jobs.values()].sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }

  get(id: string): Job {
    const job = this.jobs.get(id);
    if (!job) throw new NotFoundException(`Job ${id} introuvable`);
    return job;
  }

  cancel(id: string): Job {
    const job = this.get(id);
    if (job.status === 'running') {
      this.cancelRequested.add(id);
      this.running.get(id)?.kill();
      // runOne finalisera le job en 'cancelled' a la mort du process
    } else if (job.status === 'queued') {
      const i = this.queue.indexOf(id);
      if (i >= 0) this.queue.splice(i, 1);
      job.status = 'cancelled';
      job.finishedAt = new Date().toISOString();
      job.progress = { ...job.progress, step: 'failed', message: 'Annule avant demarrage' };
      this.touch(job);
    }
    return job;
  }

  // --- File d'attente -------------------------------------------------

  private async drain(): Promise<void> {
    if (this.processing) return;
    this.processing = true;
    try {
      while (this.queue.length > 0) {
        const id = this.queue.shift()!;
        const job = this.jobs.get(id);
        if (!job || job.status === 'cancelled') continue;
        await this.runOne(job);
      }
    } finally {
      this.processing = false;
    }
  }

  private async runOne(job: Job): Promise<void> {
    job.status = 'running';
    job.startedAt = new Date().toISOString();
    job.lastOutputAt = job.startedAt;
    job.stalled = false;
    job.progress = { step: 'idea', percent: 1, message: 'Demarrage...' };
    this.touch(job);

    const watchdog = this.startWatchdog(job);

    const handle = this.runner.run(job.params, job.outDir, {
      onProgress: (patch: Partial<JobProgress>) => {
        // Une etape qui avance annule une attente en cours : sinon le compteur
        // "attente du modele" resterait affiche apres la fin de cette attente.
        const clearWait =
          patch.waitingSeconds === undefined
            ? { waitingSeconds: undefined, waitingMax: undefined }
            : {};
        job.progress = { ...job.progress, ...clearWait, ...patch };
        this.touch(job, false);
      },
      onLogLine: (line: string) => {
        job.lastOutputAt = new Date().toISOString();
        if (job.stalled) {
          // Le process reparle : on le signale explicitement, sinon l'alerte
          // de blocage resterait a l'ecran alors que tout est reparti.
          job.stalled = false;
          this.addIncident(job, {
            level: 'warn',
            kind: 'stall',
            message: 'Le process a repris apres une periode sans reponse',
          });
        }
        job.logTail.push(line);
        if (job.logTail.length > MAX_LOG_LINES) job.logTail.shift();
        const video = this.extractFinalVideo(line, job.outDir);
        if (video) job.videoPath = video;
      },
      onIncident: (incident: ParsedIncident) => {
        this.addIncident(job, incident);
      },
    });

    this.running.set(job.id, handle);
    const { ok, code } = await handle.done;
    this.running.delete(job.id);
    clearInterval(watchdog);

    job.finishedAt = new Date().toISOString();
    job.stalled = false;
    if (this.cancelRequested.delete(job.id)) {
      job.status = 'cancelled';
      job.progress = { ...job.progress, step: 'failed', message: 'Annule' };
    } else if (ok && job.videoPath && fs.existsSync(job.videoPath)) {
      job.status = 'done';
      job.progress = { ...job.progress, step: 'done', percent: 100, message: 'Video prete' };
    } else {
      const producedVideo = Boolean(job.videoPath && fs.existsSync(job.videoPath));
      job.failure = diagnose(job.logTail, job.incidents, producedVideo, ok);
      job.status = 'failed';
      job.error = ok
        ? job.failure.summary
        : `${job.failure.summary} (code de sortie ${code ?? 'inconnu'})`;
      job.progress = { ...job.progress, step: 'failed', message: job.error };
    }
    this.touch(job);
    this.logger.log(
      `Job ${job.id} -> ${job.status}` +
        (job.failure ? ` [${job.failure.kind}]` : '') +
        ` (${job.incidents.length} incident(s))`,
    );
  }

  private addIncident(job: Job, incident: ParsedIncident): void {
    const full: JobIncident = { at: new Date().toISOString(), ...incident };
    job.incidents.push(full);
    if (job.incidents.length > MAX_INCIDENTS) job.incidents.shift();
    this.touch(job, false);
  }

  /**
   * Surveille le silence du process. Une generation normale parle en continu ;
   * un blocage (API qui ne repond plus, process fige) se traduit par un arret
   * total de la sortie, que rien d'autre ne detecterait - le job resterait
   * "en cours" indefiniment sans que personne ne le sache.
   */
  private startWatchdog(job: Job): NodeJS.Timeout {
    const timer = setInterval(() => {
      if (job.status !== 'running' || job.stalled) return;
      const last = job.lastOutputAt ? Date.parse(job.lastOutputAt) : Date.now();
      const silence = Date.now() - last;
      if (silence < STALL_MS) return;
      job.stalled = true;
      this.addIncident(job, {
        level: 'error',
        kind: 'stall',
        message: `Aucune reponse depuis ${Math.round(silence / 60000)} min — le process est peut-etre bloque`,
      });
      this.touch(job);
    }, STALL_CHECK_MS);
    timer.unref?.();
    return timer;
  }

  /**
   * Extrait le chemin de la video finale de la ligne "=== TERMINE : ... ===",
   * en verifiant qu'il reste bien dans le dossier du job (le chemin vient de
   * la sortie d'un process externe : on ne le sert jamais sans validation).
   */
  private extractFinalVideo(line: string, outDir: string): string | undefined {
    const m = /^=== TERMINE\s*:\s*(.+?)\s*===$/.exec(line.trim());
    if (!m) return undefined;
    const resolved = path.resolve(m[1].trim());
    const root = path.resolve(outDir);
    const inside = resolved === root || resolved.startsWith(root + path.sep);
    if (!inside) {
      this.logger.warn(`Chemin video hors du dossier du job, ignore : ${resolved}`);
      return undefined;
    }
    return resolved;
  }

  // --- Persistance ----------------------------------------------------

  private touch(job: Job, persist = true): void {
    this.events.next({ ...job });
    if (persist) this.save();
  }

  private save(): void {
    try {
      fs.writeFileSync(this.jobsFile, JSON.stringify([...this.jobs.values()], null, 2), 'utf8');
    } catch (err) {
      this.logger.warn(`Sauvegarde des jobs impossible : ${(err as Error).message}`);
    }
  }

  private load(): void {
    if (!fs.existsSync(this.jobsFile)) return;
    try {
      const saved = JSON.parse(fs.readFileSync(this.jobsFile, 'utf8')) as Job[];
      for (const job of saved) {
        // Jobs ecrits avant l'ajout du suivi d'incidents : on ne veut pas que
        // l'interface tombe sur un tableau absent.
        job.incidents ??= [];
        // Un job "running" au demarrage = interrompu par un redemarrage du
        // serveur : le process Python est mort avec lui.
        if (job.status === 'running' || job.status === 'queued') {
          job.status = 'failed';
          job.stalled = false;
          job.error = 'Interrompu par un redemarrage du serveur';
          job.failure = {
            kind: 'cancelled-by-restart',
            summary: 'Interrompu par un redemarrage du serveur',
            hint: 'Relancer : les scenes deja produites sont reprises depuis le cache, sans nouveaux credits.',
          };
          job.progress = { ...job.progress, step: 'failed', message: job.error };
        }
        this.jobs.set(job.id, job);
      }
      this.logger.log(`${saved.length} job(s) recharges depuis le disque`);
    } catch (err) {
      this.logger.warn(`Lecture des jobs impossible : ${(err as Error).message}`);
    }
  }
}
