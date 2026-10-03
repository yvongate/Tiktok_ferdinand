import { Injectable, Logger } from '@nestjs/common';
import { ChildProcessWithoutNullStreams, spawn } from 'child_process';
import { StringDecoder } from 'string_decoder';
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

  /**
   * Chaque format a son script. PYTHON_SCRIPT_PATH reste prioritaire : c'est
   * lui qui permet de tester tout le backend contre le mock, sans API.
   */
  private scriptPour(format: JobParams['format']): string {
    if (process.env.PYTHON_SCRIPT_PATH) return process.env.PYTHON_SCRIPT_PATH;
    const fichier = format === 'graphique' ? 'graphique.py' : 'generate.py';
    return path.resolve(__dirname, '..', '..', 'python', fichier);
  }

  private get pythonBin(): string {
    return process.env.PYTHON_BIN ?? 'python';
  }

  run(
    params: JobParams,
    outDir: string,
    cacheDir: string | undefined,
    cb: RunCallbacks,
    idea?: string,
    ideaNumber?: number,
  ): RunHandle {
    const script = this.scriptPour(params.format);
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
    // Le style ne concerne que generate.py ; graphique.py l'ignorerait,
    // et le defaut vaut le comportement historique.
    if (params.format !== 'graphique' && params.style && params.style !== 'ferdinand') {
      args.push('--style', params.style);
    }
    // Idem pour la resolution : graphique.py dessine ses images localement a
    // sa propre taille et n'a pas d'option --quality.
    if (params.format !== 'graphique' && params.quality) {
      args.push('--quality', params.quality);
    }
    // Cache commun a toutes les tentatives d'un meme sujet : c'est ce qui rend
    // vraie la "reprise sans nouveaux credits" affichee apres un echec.
    if (cacheDir) args.push('--cache-dir', cacheDir);
    // Rang du sujet : le script s'en sert pour tirer charpente, ambiance et
    // voix dans un paquet battu plutot qu'au hasard a chaque fois. Sans lui,
    // deux videos publiees a la suite retombent une fois sur quatre sur la
    // meme charpente. Le format graphique le lit dans son JSON de sujet.
    if (ideaNumber !== undefined && params.format !== 'graphique') {
      args.push('--variation-index', String(ideaNumber));
    }
    // Le format graphique recoit le sujet complet en JSON (symbole, duree) ;
    // Ferdinand ne recoit qu'un titre. Sans rien, generate.py retombe sur son
    // ancien comportement : il genere dix idees et en tire une.
    if (idea) args.push(params.format === 'graphique' ? '--subject' : '--idea', idea);

    this.logger.log(`Lancement : ${this.pythonBin} ${args.join(' ')}`);

    const child: ChildProcessWithoutNullStreams = spawn(this.pythonBin, args, {
      cwd: path.dirname(script),
      // detached : le script passe l'essentiel de son temps a attendre des
      // FFmpeg lances en sous-process. Tuer Python seul les laissait tourner -
      // ils continuaient d'encoder, de tenir le fichier ouvert et de manger le
      // demi-CPU de Render apres une annulation. Un groupe permet de tuer tout
      // l'arbre d'un coup (voir tuerArbre).
      detached: process.platform !== 'win32',
      // PYTHONIOENCODING : sans elle, Python ecrit sur Windows dans la page de
      // code ANSI (cp1252) alors qu'on relit en UTF-8 juste en dessous. Tout
      // caractere non-ASCII revenait casse : "Commerzbank <?> 20 ans", et les
      // umlauts allemands (Vermogen, Gebuhren) auraient subi le meme sort dans
      // les titres affiches ET dans le nom du fichier telecharge.
      env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
    });

    // La scene courante sert a rattacher un incident a l'endroit ou il s'est
    // produit : le script Python n'a aucune raison de la repeter a chaque
    // ligne d'erreur, mais c'est l'information la plus utile a l'ecran.
    let currentScene: number | undefined;

    const traiter = (line: string) => {
      if (!line.trim()) return;
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
    };

    /**
     * Un flux n'arrive pas ligne par ligne : une coupure de paquet peut tomber
     * au milieu d'une ligne, et meme au milieu d'un caractere UTF-8. Decoder
     * chaque morceau isolement coupait donc les lignes en deux et remplacait
     * les octets orphelins par des "?". StringDecoder garde l'octet en attente,
     * et le reste de ligne attend le morceau suivant.
     *
     * Un tampon par flux : stdout et stderr arrivent entremeles, un tampon
     * commun recollerait des moities de lignes venues des deux.
     */
    const brancher = (flux: NodeJS.ReadableStream) => {
      const decodeur = new StringDecoder('utf8');
      let reste = '';
      flux.on('data', (chunk: Buffer) => {
        const morceaux = (reste + decodeur.write(chunk)).split(/\r?\n/);
        reste = morceaux.pop() ?? '';
        for (const l of morceaux) traiter(l.trimEnd());
      });
      flux.on('end', () => {
        const fin = reste + decodeur.end();
        reste = '';
        if (fin) traiter(fin.trimEnd());
      });
    };

    brancher(child.stdout);
    brancher(child.stderr);

    const done = new Promise<{ ok: boolean; code: number | null }>((resolve) => {
      child.on('close', (code) => resolve({ ok: code === 0, code }));
      child.on('error', (err) => {
        cb.onLogLine(`Erreur de lancement du process Python : ${err.message}`);
        resolve({ ok: false, code: null });
      });
    });

    return { kill: () => this.tuerArbre(child), done };
  }

  /**
   * Tue le script ET ses sous-process (FFmpeg surtout).
   *
   * `child.kill()` n'envoie le signal qu'a Python : pendant un montage, Python
   * attend dans subprocess.run et FFmpeg survit a l'annulation.
   *  - Linux/Docker : le process est chef de groupe (detached), on signale tout
   *    le groupe avec un PID negatif.
   *  - Windows : pas de groupe de signaux, taskkill /T fait le meme travail.
   */
  private tuerArbre(child: ChildProcessWithoutNullStreams): void {
    const pid = child.pid;
    if (pid === undefined) return;
    try {
      if (process.platform === 'win32') {
        spawn('taskkill', ['/pid', String(pid), '/T', '/F']);
      } else {
        process.kill(-pid, 'SIGTERM');
        // Filet : ce qui ignore SIGTERM est acheve 5s plus tard.
        const coup = setTimeout(() => {
          try {
            process.kill(-pid, 'SIGKILL');
          } catch {
            /* groupe deja disparu */
          }
        }, 5000);
        coup.unref?.();
      }
    } catch (err) {
      this.logger.warn(`Arret force impossible (pid ${pid}) : ${(err as Error).message}`);
      child.kill();
    }
  }

  /**
   * Traduit une ligne de generate.py en progression. Renvoie null si la ligne
   * n'apporte rien d'exploitable (texte du script, listes d'idees, etc.).
   */
  private parseLine(line: string): Partial<JobProgress> | null {
    const P = PythonRunnerService.STEP_PERCENT;

    // --- Bilan des scenes, juste avant la fin ---
    // Une scene qui echoue n'arrete pas le pipeline : la video sort plus
    // courte et, sans ce bilan, rigoureusement identique a une reussite.
    const bilan = /^=== BILAN\s*:\s*(\d+)\/(\d+) scenes produites/.exec(line);
    if (bilan) {
      const done = Number(bilan[1]);
      const planned = Number(bilan[2]);
      return {
        scenesDone: done,
        scenesPlanned: planned,
        message:
          done < planned
            ? `ATTENTION : ${done}/${planned} scenes seulement`
            : `${done}/${planned} scenes produites`,
      };
    }

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
      // Seuls les trois mots connus sont reconnus : tout classer en "video"
      // par defaut faisait passer une ligne inattendue pour la derniere
      // sous-etape, et donc avancer la barre a tort.
      const sceneStage: JobProgress['sceneStage'] = stageRaw.startsWith('voix')
        ? 'voix'
        : stageRaw.startsWith('image')
          ? 'image'
          : stageRaw.startsWith('video')
            ? 'video'
            : undefined;
      // 12% -> 90% reparti sur les scenes, avec un tiers par sous-etape
      const stageOffset =
        sceneStage === 'image' ? 0.34 : sceneStage === 'video' ? 0.67 : 0;
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
    const idea = /^->\s*Idee (?:choisie|imposee)\s*:\s*(.+)$/.exec(line);
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

    // "  (tentative 2/3 rejetee : ne commence pas par "Pourquoi" -> ...)"
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
