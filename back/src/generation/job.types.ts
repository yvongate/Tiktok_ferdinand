export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled';

/** Etapes du pipeline, dans l'ordre (voir python/generate.py). */
export type JobStep =
  | 'pending'
  | 'idea'
  | 'script'
  | 'duration-check'
  | 'scenes'
  | 'generating'
  | 'montage'
  | 'done'
  | 'failed';

export interface JobParams {
  /** Quel pipeline lancer : la video narree ou le graphique boursier. */
  format: 'ferdinand' | 'graphique';
  mode: 'short' | '60s';
  lang: 'en' | 'fr' | 'de';
  videoModel: 'runway' | 'seedance';
  /** Famille visuelle du format ferdinand : rendu 3D cinematique, ou
   *  collage papier documentaire. Sans effet sur le format graphique. */
  style: 'ferdinand' | 'vox';
  /** Resolution demandee au modele video ET imposee au montage. Le 1080p
   *  est plus net mais plus cher chez le fournisseur. Sans effet sur le
   *  format graphique, qui dessine ses images localement. */
  quality: '720p' | '1080p';
}

export interface JobProgress {
  step: JobStep;
  /** 0-100, estime a partir de l'etape et de l'avancement des scenes. */
  percent: number;
  /** Derniere ligne "parlante" du script Python. */
  message: string;
  sceneCurrent?: number;
  sceneTotal?: number;
  /** Sous-etape d'une scene : voix / image / video. */
  sceneStage?: 'voix' | 'image' | 'video';
  /** Titre choisi, des qu'il est connu. */
  idea?: string;
  /** Duree mesuree de la voix au controle (mode 60s). */
  durationCheck?: number;
  /** Secondes d'attente sur la tache API en cours (battement de coeur). */
  waitingSeconds?: number;
  /** Plafond d'attente avant abandon de cette tache. */
  waitingMax?: number;
  /** Bilan de fin : scenes reellement produites / scenes prevues. */
  scenesDone?: number;
  scenesPlanned?: number;
}

/** Nature d'un incident, pour colorer/filtrer l'affichage. */
export type IncidentKind =
  | 'network' // coupure, timeout socket, DNS
  | 'http' // reponse HTTP d'erreur de l'API
  | 'api-task' // tache acceptee puis echouee cote fournisseur
  | 'download' // recuperation du fichier produit
  | 'validation' // sortie du modele rejetee par nos controles
  | 'timeout' // tache jamais terminee dans le delai
  | 'scene' // une scene n'a pas pu etre produite
  | 'stall' // plus aucun signe de vie du process
  | 'fatal'; // le pipeline s'arrete

export type IncidentLevel = 'warn' | 'error';

/**
 * Un evenement anormal, retenu meme si le pipeline s'en remet. C'est la
 * difference entre "ca a mis 40 minutes" et "ca a mis 40 minutes parce que
 * Runway a echoue 3 fois sur la scene 7".
 */
export interface JobIncident {
  at: string;
  level: IncidentLevel;
  kind: IncidentKind;
  message: string;
  /** Scene concernee, quand l'incident arrive pendant la boucle des scenes. */
  scene?: number;
  /** Tentative en cours / total, quand la ligne d'origine le precise. */
  attempt?: number;
  maxAttempts?: number;
}

/** Diagnostic lisible d'un echec, deduit des logs (voir diagnose.ts). */
export interface JobFailure {
  kind:
    | 'api-key-missing'
    | 'api-key-rejected'
    | 'quota'
    | 'credits'
    | 'network'
    | 'ffmpeg-missing'
    | 'python-missing'
    | 'cancelled-by-restart'
    | 'no-video'
    | 'data-source'
    | 'killed-stalled'
    | 'unknown';
  /** Phrase affichable telle quelle. */
  summary: string;
  /** Que faire concretement. */
  hint: string;
}

export interface Job {
  id: string;
  params: JobParams;
  status: JobStatus;
  progress: JobProgress;
  createdAt: string;
  startedAt?: string;
  finishedAt?: string;
  /** Chemin absolu de la video finale, une fois terminee. */
  videoPath?: string;
  /**
   * Legende prete a coller sous la video sur TikTok, redigee a partir du
   * script reellement dit. Sans elle, chaque publication demandait encore un
   * aller-retour manuel pour ecrire un texte et des hashtags.
   */
  description?: string;
  /** Dossier de travail isole de ce job. */
  outDir: string;
  /** Numero de l'idee reservee dans la liste validee, quand il y en a une.
   *  Elle n'est marquee consommee qu'a la reussite du job. */
  ideaNumber?: number;
  error?: string;
  /** Diagnostic exploitable de l'echec (absent si le job n'a pas echoue). */
  failure?: JobFailure;
  /** Incidents rencontres, y compris ceux dont le pipeline s'est remis. */
  incidents: JobIncident[];
  /** Horodatage de la derniere ligne recue du process Python. */
  lastOutputAt?: string;
  /** Vrai quand le process n'a plus rien emis depuis trop longtemps. */
  stalled?: boolean;
  /**
   * Job termine AVEC une video, mais amputee : des scenes ont echoue en cours
   * de route et le pipeline a continue sans elles. Sans ce drapeau, une video
   * de 58s au lieu de 75s se presente exactement comme une reussite complete -
   * c'est precisement ce qui est arrive le 27/09 (credits epuises a la scene 12).
   */
  degraded?: boolean;
  /** Dernieres lignes de log, pour debug depuis l'UI. */
  logTail: string[];
  /**
   * Renseignes UNIQUEMENT dans la liste d'historique, ou logTail et incidents
   * sont vides pour ne pas transporter des megaoctets inutiles : sur 14,5 Ko
   * par job, 14,4 Ko sont des logs que la liste n'affiche jamais.
   */
  incidentCount?: number;
  errorCount?: number;
}
