import {
  BadRequestException,
  Injectable,
  Logger,
  NotFoundException,
  OnModuleInit,
} from '@nestjs/common';
import { randomUUID } from 'crypto';
import * as fs from 'fs';
import * as path from 'path';
import { Subject } from 'rxjs';
import { diagnose } from './diagnose';
import type { Job, JobIncident, JobParams, JobProgress } from './job.types';
import { IdeasService, titreIdee } from './ideas.service';
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
 * Silence au-dela duquel on ne signale plus, on TUE.
 *
 * Le watchdog se contentait de lever un drapeau : un process reellement fige
 * restait "en cours" indefiniment et, comme la file est sequentielle, bloquait
 * TOUTES les generations suivantes jusqu'a un redemarrage manuel du serveur.
 *
 * 20 minutes : la plus longue attente legitime est une tache video (plafond
 * 600s), et le script emet un battement toutes les ~24s pendant cette attente.
 * Vingt minutes sans la moindre ligne ne correspond a aucun fonctionnement
 * normal.
 */
const KILL_AFTER_MS = 20 * 60 * 1000;

/** Duree totale au-dela de laquelle un job est abandonne, meme bavard. */
const MAX_JOB_MS = 3 * 60 * 60 * 1000;

/** Jobs conserves dans l'historique (les plus anciens sont oublies). */
const MAX_JOBS = 200;

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
  /** Jobs tues par le watchdog : a distinguer d'une annulation volontaire,
   *  sinon l'ecran affiche "Annule" pour quelque chose que personne n'a annule. */
  private readonly killRequested = new Set<string>();

  /** Flux d'evenements pour le SSE (un evenement par mise a jour de job). */
  readonly events = new Subject<Job>();

  constructor(
    private readonly runner: PythonRunnerService,
    private readonly ideas: IdeasService,
  ) {}

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

  /**
   * Supprime definitivement un job : son dossier de travail, sa video, et son
   * entree dans l'historique.
   *
   * Refuse tant que le job tourne ou attend : il faut l'annuler d'abord,
   * sinon on effacerait des fichiers sous les pieds du process Python.
   */
  remove(id: string): { id: string; freed: number } {
    const job = this.get(id);
    if (job.status === 'running' || job.status === 'queued') {
      throw new BadRequestException(
        "Ce job est en cours : annule-le avant de le supprimer.",
      );
    }

    let freed = 0;
    try {
      const mesurer = (dossier: string): void => {
        for (const e of fs.readdirSync(dossier, { withFileTypes: true })) {
          const complet = path.join(dossier, e.name);
          if (e.isDirectory()) mesurer(complet);
          else freed += fs.statSync(complet).size;
        }
      };
      if (fs.existsSync(job.outDir)) {
        mesurer(job.outDir);
        fs.rmSync(job.outDir, { recursive: true, force: true });
      }
    } catch (err) {
      this.logger.warn(`Suppression partielle de ${id} : ${(err as Error).message}`);
    }

    this.jobs.delete(id);
    this.save();
    this.logger.log(`Job ${id} supprime (${(freed / 1048576).toFixed(1)} Mo liberes)`);
    return { id, freed };
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

    // L'idee est RESERVEE ici mais consommee seulement a la reussite : un
    // job echoue ou annule doit pouvoir etre relance sur le meme titre.
    const idea = this.ideas.peek(job.params.format);
    if (idea) {
      job.ideaNumber = idea.n;
      job.progress = { ...job.progress, idea: titreIdee(idea) };
    }
    // Ferdinand recoit un titre, le format graphique le sujet complet en
    // JSON (symbole et duree, dont le script a besoin pour charger la serie).
    const charge = idea
      ? job.params.format === 'graphique'
        ? JSON.stringify(idea)
        : (idea.de ?? '')
      : undefined;

    const handle = this.runner.run(job.params, job.outDir, this.cacheDir(job), {
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
    }, charge);

    this.running.set(job.id, handle);
    const { ok, code } = await handle.done;
    this.running.delete(job.id);
    clearInterval(watchdog);

    job.finishedAt = new Date().toISOString();
    job.stalled = false;
    const tueParWatchdog = this.killRequested.delete(job.id);
    if (tueParWatchdog) {
      job.status = 'failed';
      job.failure = {
        kind: 'killed-stalled',
        summary: 'Generation abandonnee : le process ne repondait plus',
        hint: 'Le job a ete tue pour liberer la file. Relancer : les scenes deja produites sont reprises depuis le cache, sans nouveaux credits.',
      };
      job.error = job.failure.summary;
      job.progress = { ...job.progress, step: 'failed', message: job.error };
    } else if (this.cancelRequested.delete(job.id)) {
      job.status = 'cancelled';
      job.progress = { ...job.progress, step: 'failed', message: 'Annule' };
    } else if (ok && job.videoPath && fs.existsSync(job.videoPath)) {
      job.status = 'done';
      // Une video peut etre livree ET amputee : le script continue apres une
      // scene ratee. Le bilan du script dit combien de scenes ont abouti.
      const { scenesDone, scenesPlanned } = job.progress;
      job.degraded =
        scenesDone !== undefined &&
        scenesPlanned !== undefined &&
        scenesDone < scenesPlanned;
      job.progress = {
        ...job.progress,
        step: 'done',
        percent: 100,
        message: job.degraded
          ? `Video prete mais INCOMPLETE : ${scenesDone}/${scenesPlanned} scenes`
          : 'Video prete',
      };
      // Une video amputee ne consomme PAS le sujet : il doit rester le
      // prochain de la liste pour etre relance, et son cache de scenes est
      // conserve pour ne repayer que les scenes manquantes.
      if (job.ideaNumber !== undefined && !job.degraded) {
        this.ideas.markUsed(job.params.format, job.ideaNumber);
        this.viderCache(job);
      }
      this.purgeIntermediates(job);
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

  /**
   * Supprime les fichiers de travail d'un job REUSSI, en ne gardant que la
   * video finale.
   *
   * Un job Ferdinand conserve environ 200 Mo de fichiers intermediaires
   * (concats, clips de scene, voix, images gelees) pour 11 Mo utiles : sans
   * ce menage, vingt-cinq videos suffisent a remplir un disque de 5 Go.
   *
   * Uniquement a la REUSSITE : tant qu'un job echoue, ses scenes deja
   * produites permettent de le relancer sans repayer les credits. Une fois la
   * video livree, cette reprise n'a plus d'objet.
   */
  private purgeIntermediates(job: Job): void {
    if (!job.videoPath) return;
    const garder = path.resolve(job.videoPath);
    let liberes = 0;

    const parcourir = (dossier: string): void => {
      let entrees: fs.Dirent[];
      try {
        entrees = fs.readdirSync(dossier, { withFileTypes: true });
      } catch {
        return;
      }
      for (const entree of entrees) {
        const complet = path.join(dossier, entree.name);
        if (entree.isDirectory()) {
          parcourir(complet);
          try {
            fs.rmdirSync(complet);
          } catch {
            /* dossier non vide : il contenait la video finale */
          }
          continue;
        }
        if (path.resolve(complet) === garder) continue;
        try {
          liberes += fs.statSync(complet).size;
          fs.unlinkSync(complet);
        } catch {
          /* non bloquant : un fichier verrouille ne doit pas faire echouer
             un job par ailleurs reussi */
        }
      }
    };

    try {
      parcourir(job.outDir);
    } catch (err) {
      this.logger.warn(`Purge incomplete pour ${job.id} : ${(err as Error).message}`);
      return;
    }
    if (liberes > 0) {
      this.logger.log(
        `Job ${job.id} : ${(liberes / 1048576).toFixed(1)} Mo de fichiers de travail supprimes`,
      );
    }
  }

  /**
   * Dossier de cache des scenes, commun a toutes les tentatives d'UN MEME
   * sujet.
   *
   * Il etait jusqu'ici confondu avec le dossier de travail du job, lui-meme
   * cree avec un identifiant neuf a chaque lancement : la "reprise depuis le
   * cache" promise par l'interface et par diagnose.ts ne pouvait donc jamais
   * avoir lieu - relancer un job echoue repayait l'integralite des scenes.
   * Indexe sur le numero du sujet, il survit d'une tentative a l'autre.
   */
  private cacheDir(job: Job): string | undefined {
    if (job.ideaNumber === undefined) return undefined;
    return path.join(this.dataDir, 'cache', `${job.params.format}-${job.ideaNumber}`);
  }

  /** Efface le cache d'un sujet mene a terme : il n'a plus rien a reprendre. */
  private viderCache(job: Job): void {
    const dir = this.cacheDir(job);
    if (!dir) return;
    try {
      fs.rmSync(dir, { recursive: true, force: true });
    } catch (err) {
      this.logger.warn(`Cache non efface (${dir}) : ${(err as Error).message}`);
    }
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
      if (job.status !== 'running') return;
      const last = job.lastOutputAt ? Date.parse(job.lastOutputAt) : Date.now();
      const silence = Date.now() - last;
      const debut = job.startedAt ? Date.parse(job.startedAt) : Date.now();
      const total = Date.now() - debut;

      // Abandon : signaler ne suffit pas, la file resterait bloquee derriere.
      const motif =
        silence >= KILL_AFTER_MS
          ? `aucune reponse depuis ${Math.round(silence / 60000)} min`
          : total >= MAX_JOB_MS
            ? `duree totale de ${Math.round(total / 3600000)} h depassee`
            : null;
      if (motif) {
        this.killRequested.add(job.id);
        this.addIncident(job, {
          level: 'error',
          kind: 'stall',
          message: `Job abandonne : ${motif}. Le process a ete tue pour liberer la file.`,
        });
        this.logger.warn(`Job ${job.id} tue par le watchdog (${motif})`);
        this.running.get(job.id)?.kill();
        this.touch(job);
        return;
      }

      if (job.stalled || silence < STALL_MS) return;
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

  /**
   * Oublie les jobs les plus anciens. L'historique n'avait aucune borne :
   * jobs.json grossit d'environ 25 Ko par generation (le journal en represente
   * la quasi-totalite) et etait reecrit en entier a chaque sauvegarde.
   *
   * Seule l'ENTREE d'historique disparait : les fichiers ont deja ete purges a
   * la reussite, et une suppression de video reste un geste explicite.
   */
  private oublierLesPlusAnciens(): void {
    if (this.jobs.size <= MAX_JOBS) return;
    const tries = this.list(); // du plus recent au plus ancien
    for (const job of tries.slice(MAX_JOBS)) {
      if (job.status === 'running' || job.status === 'queued') continue;
      this.jobs.delete(job.id);
    }
  }

  private save(): void {
    try {
      this.oublierLesPlusAnciens();
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
