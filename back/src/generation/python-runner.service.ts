import { Injectable, Logger } from '@nestjs/common';
import { ChildProcessWithoutNullStreams, spawn } from 'child_process';
import * as path from 'path';
import type { JobIncident, JobParams, JobProgress } from './job.types';

/** Incident detecte dans la sortie, avant horodatage. */
export type ParsedIncident = Omit<JobIncident, 'at'>;

export interface RunHandle {
  /** Tue le process Python (annulation d'un job). */
  kill: () => void;
  /** Resolue a la fin du process : ok=false si code de sortie != 0. */
  done: Promise<{ ok: boolean; code: number | null }>;
}

export interface RunCallbacks {
  onProgress: (patch: Partial<JobProgress>) => void;
  onLogLine: (line: string) => void;
  onIncident: (incident: ParsedIncident) => void;
}

/**
 * Lance python/generate.py et traduit sa sortie texte en progression
 * structuree. Le script Python reste la source de verite de la generation -
 * ce service ne fait que l'orchestrer et l'observer.
 */
@Injectable()
export class PythonRunnerService {
  private readonly logger = new Logger(PythonRunnerService.name);

  /** Poids de chaque etape dans la barre de progression (0-100). */
  private static readonly STEP_PERCENT: Record<string, number> = {
    pending: 0,
    idea: 3,
    script: 6,
    'duration-check': 9,
    scenes: 12,
    // 'generating' est calcule au prorata des scenes : 12 -> 90
    montage: 93,
    done: 100,
  };

  private get scriptPath(): string {
    return (
      process.env.PYTHON_SCRIPT_PATH ??
      path.resolve(__dirname, '..', '..', 'python', 'generate.py')
    );
  }

  private get pythonBin(): string {
    return process.env.PYTHON_BIN ?? 'python';
  }

  run(params: JobParams, outDir: string, cb: RunCallbacks, idea?: string): RunHandle {
    const script = this.scriptPath;
    const args = [
      '-u', // sortie non bufferisee : indispensable pour la progression live
      script,
      '--mode',
      params.mode,
      '--lang',
      params.lang,
      '--video-model',
      params.videoModel,
      '--out-dir',
      outDir,
    ];
    // Sans idee imposee, le script retombe sur son ancien comportement : il
    // en genere dix et en tire une. C'est le repli si la liste validee est
    // absente ou epuisee.
    if (idea) args.push('--idea', idea);

    this.logger.log(`Lancement : ${this.pythonBin} ${args.join(' ')}`);

    const child: ChildProcessWithoutNullStreams = spawn(this.pythonBin, args, {
      cwd: path.dirname(script),
      env: { ...process.env },
    });

    // La scene courante sert a rattacher un incident a l'endroit ou il s'est
    // produit : le script Python n'a aucune raison de la repeter a chaque
    // ligne d'erreur, mais c'est l'information la plus utile a l'ecran.
    let currentScene: number | undefined;

    const handleChunk = (chunk: Buffer) => {
      for (const rawLine of chunk.toString('utf8').split(/\r?\n/)) {
        const line = rawLine.trimEnd();
        if (!line.trim()) continue;
        cb.onLogLine(line);

        const patch = this.parseLine(line);
        if (patch) {
          if (patch.sceneCurrent) currentScene = patch.sceneCurrent;
          cb.onProgress(patch);
        }

        const incident = this.parseIncident(line);
        if (incident) {
          cb.onIncident({ scene: currentScene, ...incident });
        }
      }
    };

    child.stdout.on('data', handleChunk);
    child.stderr.on('data', handleChunk);

    const done = new Promise<{ ok: boolean; code: number | null }>((resolve) => {
      child.on('close', (code) => resolve({ ok: code === 0, code }));
      child.on('error', (err) => {
        cb.onLogLine(`Erreur de lancement du process Python : ${err.message}`);
        resolve({ ok: false, code: null });
      });
    });

    return { kill: () => child.kill(), done };
  }

  /**
   * Traduit une ligne de generate.py en progression. Renvoie null si la ligne
   * n'apporte rien d'exploitable (texte du script, listes d'idees, etc.).
   */
  private parseLine(line: string): Partial<JobProgress> | null {
    const P = PythonRunnerService.STEP_PERCENT;

    // --- Fin ---
    const termine = /^=== TERMINE\s*:\s*(.+?)\s*===$/.exec(line);
    if (termine) {
      return {
        step: 'done',
        percent: 100,
        message: 'Video terminee',
        // videoPath est extrait par JobsService (il valide le chemin)
      };
    }

    // --- Scenes : "=== Scene 4/15 : voix ===" ---
    const scene = /^=== Scene (\d+)\/(\d+)(?:\s*\[[^\]]*\])?\s*:\s*([a-zA-Zéè]+)/.exec(line);
    if (scene) {
      const current = Number(scene[1]);
      const total = Number(scene[2]);
      const stageRaw = scene[3].toLowerCase();
      const sceneStage: JobProgress['sceneStage'] =
        stageRaw.startsWith('voix') ? 'voix' : stageRaw.startsWith('image') ? 'image' : 'video';
      // 12% -> 90% reparti sur les scenes, avec un tiers par sous-etape
      const stageOffset = sceneStage === 'voix' ? 0 : sceneStage === 'image' ? 0.34 : 0.67;
      const sceneFraction = total > 0 ? (current - 1 + stageOffset) / total : 0;
      return {
        step: 'generating',
        percent: Math.round(12 + sceneFraction * 78),
        message: `Scene ${current}/${total} — ${sceneStage}`,
        sceneCurrent: current,
        sceneTotal: total,
        sceneStage,
      };
    }

    // --- Etapes nommees ---
    if (/^=== .*Generation de l'idee/.test(line)) {
      return { step: 'idea', percent: P.idea, message: "Generation de l'idee" };
    }
    if (/^=== .*Generation du script/.test(line)) {
      return { step: 'script', percent: P.script, message: 'Ecriture du script' };
    }
    if (/^=== .*Decoupage en scenes/.test(line)) {
      return { step: 'scenes', percent: P.scenes, message: 'Decoupage en scenes' };
    }
    if (/^=== .*Generation scene par scene/.test(line)) {
      return { step: 'generating', percent: P.scenes, message: 'Generation des scenes' };
    }
    if (/^=== .*Montage FFmpeg/.test(line)) {
      return { step: 'montage', percent: P.montage, message: 'Montage final' };
    }
    if (/^=== .*Reprise depuis le cache/.test(line)) {
      return { step: 'scenes', percent: P.scenes, message: 'Reprise depuis le cache' };
    }

    // --- Battement de coeur pendant l'attente d'une tache API ---
    // Sans ca, l'interface reste figee sur le meme message jusqu'a 10 minutes
    // pendant la generation video, sans moyen de distinguer une attente
    // normale d'un blocage.
    const attente = /^\s*ATTENTE (\d+)s\/(\d+)s \(etat=(.+?)\)/.exec(line);
    if (attente) {
      const [, elapsed, max, state] = attente;
      return {
        waitingSeconds: Number(elapsed),
        waitingMax: Number(max),
        message: `Attente du modele : ${elapsed}s (etat ${state})`,
      };
    }

    // --- Details utiles ---
    const idea = /^->\s*Idee choisie\s*:\s*(.+)$/.exec(line);
    if (idea) {
      return { idea: idea[1].trim(), message: `Idee : ${idea[1].trim()}` };
    }

    const controle = /Controle duree\s*:\s*([\d.]+)s/.exec(line);
    if (controle) {
      return {
        step: 'duration-check',
        percent: P['duration-check'],
        durationCheck: Number(controle[1]),
        message: `Controle de duree : ${controle[1]}s`,
      };
    }

    const nouvelleDuree = /Nouvelle duree\s*:\s*([\d.]+)s/.exec(line);
    if (nouvelleDuree) {
      return {
        step: 'duration-check',
        durationCheck: Number(nouvelleDuree[1]),
        message: `Script rallonge : ${nouvelleDuree[1]}s`,
      };
    }

    if (/scenes generees/.test(line)) {
      const n = /^(\d+) scenes generees/.exec(line);
      return {
        step: 'scenes',
        percent: P.scenes,
        sceneTotal: n ? Number(n[1]) : undefined,
        message: line.trim(),
      };
    }

    // --- Avertissements / erreurs non fatales : on les remonte comme message ---
    if (/^ECHEC|ECHEC\s*:|ATTENTION|Erreur reseau|Erreur telechargement/.test(line)) {
      return { message: line.trim() };
    }

    return null;
  }

  /**
   * Repere les lignes anormales et les classe.
   *
   * Ces lignes existaient deja dans generate.py mais finissaient noyees dans
   * le journal : un retry reseau a la scene 7 etait indiscernable du reste.
   * Les isoler permet de montrer, pendant et apres la generation, ce qui s'est
   * reellement mal passe - y compris quand le pipeline s'en est remis tout seul.
   */
  private parseIncident(raw: string): Omit<ParsedIncident, 'scene'> | null {
    const line = raw.trim();

    // "  Erreur reseau (TimeoutError): ..."
    if (/^Erreur reseau \(/.test(line)) {
      return { level: 'warn', kind: 'network', message: line };
    }

    // "  HTTP 429: {...}" - une reponse d'erreur de l'API
    const http = /^HTTP (\d{3})\s*:\s*(.*)$/.exec(line);
    if (http) {
      const code = Number(http[1]);
      return {
        level: code === 429 || code >= 500 ? 'warn' : 'error',
        kind: 'http',
        message: `HTTP ${code} — ${http[2].slice(0, 200)}`,
      };
    }

    // "  Erreur telechargement (X): ... - (retry 2/4)"
    const dl = /^Erreur telechargement \(([^)]+)\):\s*(.*?)\s*-\s*\(retry (\d+)\/(\d+)\)/.exec(line);
    if (dl) {
      return {
        level: 'warn',
        kind: 'download',
        message: `Telechargement echoue (${dl[1]}) : ${dl[2].slice(0, 200)}`,
        attempt: Number(dl[3]),
        maxAttempts: Number(dl[4]),
      };
    }

    // "  (retry 2/4 apres echec GPT-5.2)" / "  (retry 2/3)"
    const retry = /^\(retry (\d+)\/(\d+)(?:\s+(.*?))?\)$/.exec(line);
    if (retry) {
      return {
        level: 'warn',
        kind: 'network',
        message: retry[3] ? `Nouvelle tentative ${retry[3]}` : 'Nouvelle tentative apres echec',
        attempt: Number(retry[1]),
        maxAttempts: Number(retry[2]),
      };
    }

    // "    (tache runway echouee, nouvelle tentative 2/3)"
    const task = /^\(tache (\S+) echouee, nouvelle tentative (\d+)\/(\d+)\)$/.exec(line);
    if (task) {
      return {
        level: 'warn',
        kind: 'api-task',
        message: `Tache ${task[1]} echouee cote fournisseur, relance complete`,
        attempt: Number(task[2]),
        maxAttempts: Number(task[3]),
      };
    }

    // "    ECHEC : internal error, please try again later"
    const failMsg = /^ECHEC\s*:\s*(.+)$/.exec(line);
    if (failMsg && !/^ECHEC total/.test(line)) {
      return { level: 'error', kind: 'api-task', message: `Tache refusee : ${failMsg[1]}` };
    }

    // "    Timeout apres 600s (dernier etat=waiting)."
    const timeout = /^Timeout apres (\d+)s(?:\s*\(dernier etat=(.+?)\))?/.exec(line);
    if (timeout) {
      return {
        level: 'error',
        kind: 'timeout',
        message: `Tache jamais terminee apres ${timeout[1]}s${
          timeout[2] ? ` (dernier etat : ${timeout[2]})` : ''
        }`,
      };
    }

    // "  (tentative 2/3 rejetee : ne commence pas par "Voici pourquoi" -> ...)"
    const rejected = /^\(tentative (\d+)\/(\d+) rejetee\s*:\s*(.+?)\)$/.exec(line);
    if (rejected) {
      return {
        level: 'warn',
        kind: 'validation',
        message: `Sortie du modele rejetee : ${rejected[3].slice(0, 200)}`,
        attempt: Number(rejected[1]),
        maxAttempts: Number(rejected[2]),
      };
    }

    // Echecs de scene : le pipeline continue, mais il manquera quelque chose.
    const sceneFail =
      /^Echec (voix de la scene|generation image|generation video|telechargement video)/.exec(line);
    if (sceneFail) {
      return { level: 'error', kind: 'scene', message: `Scene incomplete : ${sceneFail[1]}` };
    }

    // "ECHEC total sur ... Arret." - le pipeline s'arrete vraiment.
    if (/^ECHEC total|^ECHEC\s*:\s*le script ne commence jamais|Arret\./.test(line)) {
      return { level: 'error', kind: 'fatal', message: line };
    }

    if (/^ATTENTION/.test(line) || /ATTENTION/.test(line)) {
      return { level: 'warn', kind: 'validation', message: line };
    }

    return null;
  }
}
