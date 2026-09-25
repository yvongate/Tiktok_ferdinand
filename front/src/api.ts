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

export interface JobParams {
  mode: 'short' | '60s'
  lang: 'en' | 'fr'
  videoModel: 'runway' | 'seedance'
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
  logTail: string[]
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

async function handle<T>(request: Promise<Response>): Promise<T> {
  const res = await request
  if (!res.ok) {
    const body = await res.text()
    throw new Error(body || `HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  create: (params: JobParams) =>
    handle<Job>(
      fetch(BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      }),
    ),

  list: () => handle<Job[]>(fetch(BASE)),

  get: (id: string) => handle<Job>(fetch(`${BASE}/${id}`)),

  cancel: (id: string) => handle<Job>(fetch(`${BASE}/${id}`, { method: 'DELETE' })),

  videoUrl: (id: string) => `${BASE}/${id}/video`,

  health: () => handle<HealthReport>(fetch(`${ROOT}/api/health`)),

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
