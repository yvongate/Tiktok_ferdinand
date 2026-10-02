export type JobStatus = 'queued' | 'running' | 'done' | 'failed' | 'cancelled'

export type JobStep =
  | 'pending'
  | 'idea'
  | 'script'
  | 'duration-check'
  | 'scenes'
  | 'generating'
  | 'montage'
  | 'done'
  | 'failed'

export type Format = 'ferdinand' | 'graphique'

export const FORMAT_LABELS: Record<Format, string> = {
  ferdinand: 'Ferdinand (video narree)',
  graphique: 'Graphique boursier',
}

export type Style = 'ferdinand' | 'vox'

export const STYLE_LABELS: Record<Style, string> = {
  ferdinand: 'Ferdinand 3D (rendu cinematique)',
  vox: 'Collage documentaire (papier decoupe)',
}

export type Quality = '720p' | '1080p'

export const QUALITY_LABELS: Record<Quality, string> = {
  '720p': '720p (defaut)',
  '1080p': '1080p (2,5x plus cher)',
}

export interface JobParams {
  format: Format
  mode: 'short' | '60s'
  lang: 'en' | 'fr' | 'de'
  videoModel: 'runway' | 'seedance'
  /** Famille visuelle, format ferdinand uniquement. */
  style: Style
  /** Resolution, format ferdinand uniquement. */
  quality: Quality
}

export interface JobProgress {
  step: JobStep
  percent: number
  message: string
  sceneCurrent?: number
  sceneTotal?: number
  sceneStage?: 'voix' | 'image' | 'video'
  idea?: string
  durationCheck?: number
  waitingSeconds?: number
  waitingMax?: number
  /** Bilan de fin : scenes reellement produites / prevues. */
  scenesDone?: number
  scenesPlanned?: number
}

export type IncidentKind =
  | 'network'
  | 'http'
  | 'api-task'
  | 'download'
  | 'validation'
  | 'timeout'
  | 'scene'
  | 'stall'
  | 'fatal'

export interface JobIncident {
  at: string
  level: 'warn' | 'error'
  kind: IncidentKind
  message: string
  scene?: number
  attempt?: number
  maxAttempts?: number
}

export interface JobFailure {
  kind: string
  summary: string
  hint: string
}

export interface Job {
  id: string
  params: JobParams
  status: JobStatus
  progress: JobProgress
  createdAt: string
  startedAt?: string
  finishedAt?: string
  videoPath?: string
  error?: string
  failure?: JobFailure
  incidents: JobIncident[]
  lastOutputAt?: string
  stalled?: boolean
  /** Video livree, mais amputee : des scenes ont echoue en chemin. */
  degraded?: boolean
  logTail: string[]
  /** Presents uniquement dans l'historique allege (logTail/incidents y sont
   *  vides pour ne pas transporter des megaoctets de logs inutiles). */
  incidentCount?: number
  errorCount?: number
}

export interface Idea {
  n: number
  // format ferdinand
  cat?: string
  /** Titre francais : relecture humaine uniquement. */
  fr?: string
  /** Titre allemand : c'est celui-ci qui part en production. */
  de?: string
  // format graphique
  nom?: string
  symbole?: string
  annees?: number
  histoire?: string
  final?: number
}

/** Libelle affichable, quel que soit le format. */
export const titreIdee = (i: Idea) => i.de ?? `${i.nom} — ${i.annees} ans`

export interface IdeasProgress {
  format: Format
  total: number
  used: number
  remaining: number
  percent: number
  next: Idea | null
}

export interface CheckResult {
  name: string
  ok: boolean
  detail: string
}

export interface HealthReport {
  ok: boolean
  checkedAt: string
  checks: CheckResult[]
}

/**
 * En developpement, VITE_API_BASE est vide : les appels partent en relatif
 * (`/api/...`) et le proxy Vite les renvoie vers localhost:3000 — meme origine,
 * donc aucun souci de CORS.
 *
 * En production le front est sur Vercel et le backend sur Render : deux
 * domaines differents. Sans base explicite, `/api/...` taperait sur Vercel,
 * qui n'a aucun backend — c'est le piege classique de ce decoupage.
 */
const ROOT = (import.meta.env.VITE_API_BASE ?? '').replace(/\/+$/, '')

const BASE = `${ROOT}/api/generation`

/**
 * Jeton d'ecriture, fige a la compilation comme VITE_API_BASE.
 *
 * Il n'ouvre aucun droit supplementaire : il empeche seulement un inconnu de
 * declencher des generations facturees sur ce compte. Il voyage en en-tete et
 * jamais dans l'URL — une URL finit dans les journaux de tous les
 * intermediaires.
 */
const TOKEN = (import.meta.env.VITE_API_TOKEN ?? '').trim()

const enTetes = (base: Record<string, string> = {}): Record<string, string> =>
  TOKEN ? { ...base, 'x-ferdinand-token': TOKEN } : base

async function handle<T>(request: Promise<Response>): Promise<T> {
  const res = await request
  if (!res.ok) {
    throw new Error(await messageErreur(res))
  }
  return res.json() as Promise<T>
}

/**
 * Nest repond une erreur en JSON ({statusCode, error, message}). Le corps brut
 * etait affiche tel quel dans le bandeau rouge : l'utilisateur lisait
 * `{"message":"Toutes les entrees...","error":"Bad Request","statusCode":400}`
 * au lieu de la phrase ecrite pour lui.
 */
async function messageErreur(res: Response): Promise<string> {
  const brut = await res.text()
  if (!brut) return `Erreur ${res.status}`
  try {
    const json = JSON.parse(brut) as { message?: string | string[] }
    const m = json.message
    if (Array.isArray(m) && m.length) return m.join(' · ')
    if (typeof m === 'string' && m) return m
  } catch {
    /* pas du JSON : le texte brut fait deja l'affaire */
  }
  return brut
}

export const api = {
  create: (params: JobParams) =>
    handle<Job>(
      fetch(BASE, {
        method: 'POST',
        headers: enTetes({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(params),
      }),
    ),

  list: () => handle<Job[]>(fetch(BASE)),

  get: (id: string) => handle<Job>(fetch(`${BASE}/${id}`)),

  /** Annule si le job tourne, le SUPPRIME (fichiers compris) s'il est termine. */
  cancelOrDelete: (id: string) =>
    handle<Job | { id: string; freed: number }>(
      fetch(`${BASE}/${id}`, { method: 'DELETE', headers: enTetes() }),
    ),

  videoUrl: (id: string) => `${BASE}/${id}/video`,

  /** Meme fichier, mais servi en piece jointe (voir Content-Disposition cote
   *  backend) : l'attribut `download` d'un lien ne suffit pas entre domaines. */
  downloadUrl: (id: string) => `${BASE}/${id}/video?download=1`,

  health: () => handle<HealthReport>(fetch(`${ROOT}/api/health`)),

  ideas: () => handle<IdeasProgress[]>(fetch(`${BASE}/ideas`)),

  /** Suivi live d'un job. Renvoie une fonction de nettoyage. */
  subscribe: (id: string, onJob: (job: Job) => void): (() => void) => {
    const source = new EventSource(`${BASE}/${id}/events`)
    source.onmessage = (evt) => {
      try {
        onJob(JSON.parse(evt.data) as Job)
      } catch {
        /* ignore les messages non-JSON (keep-alive) */
      }
    }
    // En cas de coupure, EventSource se reconnecte tout seul ; on ferme
    // seulement quand le composant se demonte.
    return () => source.close()
  },
}

export const INCIDENT_LABELS: Record<IncidentKind, string> = {
  network: 'Reseau',
  http: 'Reponse API',
  'api-task': 'Tache API',
  download: 'Telechargement',
  validation: 'Sortie rejetee',
  timeout: 'Delai depasse',
  scene: 'Scene',
  stall: 'Blocage',
  fatal: 'Arret',
}

export const STEP_LABELS: Record<JobStep, string> = {
  pending: 'En attente',
  idea: "Recherche d'idee",
  script: 'Ecriture du script',
  'duration-check': 'Controle de duree',
  scenes: 'Decoupage en scenes',
  generating: 'Generation des scenes',
  montage: 'Montage final',
  done: 'Termine',
  failed: 'Echec',
}
