import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import {
  api,
  INCIDENT_LABELS,
  STEP_LABELS,
  type HealthReport,
  type Job,
  type JobIncident,
  type JobParams,
} from './api'

const ACTIVE: Job['status'][] = ['queued', 'running']

const time = (iso: string) => new Date(iso).toLocaleTimeString('fr-FR')

/** Nombre d'incidents, que le job vienne de l'historique allege ou du SSE. */
const incidentTotal = (job: Job) => job.incidentCount ?? job.incidents?.length ?? 0

/** "il y a 2 min 10" — un compteur fige est deja une information. */
function since(iso: string, now: number): string {
  const s = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))
  if (s < 60) return `${s} s`
  return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')}`
}

function App() {
  const [params, setParams] = useState<JobParams>({
    mode: '60s',
    lang: 'fr',
    videoModel: 'runway',
  })
  const [jobs, setJobs] = useState<Job[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [launching, setLaunching] = useState(false)
  const [health, setHealth] = useState<HealthReport | null>(null)
  const unsubscribe = useRef<(() => void) | null>(null)

  const upsert = useCallback((job: Job) => {
    setJobs((prev) => {
      const i = prev.findIndex((j) => j.id === job.id)
      if (i === -1) return [job, ...prev]
      const next = [...prev]
      next[i] = job
      return next
    })
  }, [])

  // Chargement initial de l'historique + reprise du suivi si un job tourne deja
  useEffect(() => {
    api
      .list()
      .then((list) => {
        setJobs(list)
        const active = list.find((j) => ACTIVE.includes(j.status))
        if (active) setSelectedId(active.id)
      })
      .catch((e: Error) => setError(e.message))
    api.health().then(setHealth).catch(() => setHealth(null))
  }, [])

  // Suivi live du job selectionne
  useEffect(() => {
    unsubscribe.current?.()
    unsubscribe.current = null
    if (!selectedId) return
    unsubscribe.current = api.subscribe(selectedId, upsert)
    return () => {
      unsubscribe.current?.()
      unsubscribe.current = null
    }
  }, [selectedId, upsert])

  const selected = jobs.find((j) => j.id === selectedId) ?? null

  const launch = async () => {
    setError(null)
    setLaunching(true)
    try {
      const job = await api.create(params)
      upsert(job)
      setSelectedId(job.id)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLaunching(false)
    }
  }

  const cancel = async (id: string) => {
    try {
      upsert(await api.cancel(id))
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const hasActive = jobs.some((j) => ACTIVE.includes(j.status))

  return (
    <div className="app">
      <header>
        <h1>Ferdinand Renard</h1>
        <p className="subtitle">Generateur de shorts « Voici pourquoi »</p>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <HealthBanner health={health} onRefresh={() => api.health().then(setHealth).catch(() => {})} />

      <section className="panel">
        <h2>Nouvelle video</h2>
        <div className="form">
          <label>
            Format
            <select
              value={params.mode}
              onChange={(e) => setParams({ ...params, mode: e.target.value as JobParams['mode'] })}
            >
              <option value="60s">60s (duree garantie, monetisable)</option>
              <option value="short">Court (histoire resserree)</option>
            </select>
          </label>

          <label>
            Langue
            <select
              value={params.lang}
              onChange={(e) => setParams({ ...params, lang: e.target.value as JobParams['lang'] })}
            >
              <option value="fr">Francais</option>
              <option value="en">Anglais</option>
            </select>
          </label>

          <label>
            Modele video
            <select
              value={params.videoModel}
              onChange={(e) =>
                setParams({ ...params, videoModel: e.target.value as JobParams['videoModel'] })
              }
            >
              <option value="runway">Runway (defaut)</option>
              <option value="seedance">Seedance (repli)</option>
            </select>
          </label>

          <button onClick={launch} disabled={launching || hasActive}>
            {launching ? 'Lancement...' : hasActive ? 'Generation en cours...' : 'Lancer la generation'}
          </button>
        </div>
        {hasActive && (
          <p className="hint">
            Une seule generation a la fois — la suivante sera mise en file d'attente.
          </p>
        )}
      </section>

      {selected && <JobDetail job={selected} onCancel={cancel} />}

      <section className="panel">
        <h2>Historique</h2>
        {jobs.length === 0 && <p className="hint">Aucune generation pour le moment.</p>}
        <ul className="history">
          {jobs.map((job) => (
            <li
              key={job.id}
              className={job.id === selectedId ? 'selected' : ''}
              onClick={() => setSelectedId(job.id)}
            >
              <span className={`badge ${job.status}`}>{job.status}</span>
              <span className="history-title">
                {job.progress.idea ?? STEP_LABELS[job.progress.step]}
              </span>
              <span className="history-meta">
                {job.params.mode} · {job.params.lang} · {job.params.videoModel}
                {/* incidentCount vient de l'historique allege ; incidents du
                    flux SSE, qui remplace l'entree par le job complet. */}
                {incidentTotal(job) > 0 && (
                  <span className="pill warn">{incidentTotal(job)} incident(s)</span>
                )}
              </span>
              <span className="history-date">
                {new Date(job.createdAt).toLocaleString('fr-FR')}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

/**
 * Etat du serveur avant toute generation : cle API, Python, FFmpeg, disque.
 * Ne s'affiche que si quelque chose manque — un bandeau vert permanent
 * finirait par ne plus etre lu.
 */
function HealthBanner({
  health,
  onRefresh,
}: {
  health: HealthReport | null
  onRefresh: () => void
}) {
  if (!health || health.ok) return null
  const broken = health.checks.filter((c) => !c.ok)
  return (
    <div className="health-banner">
      <strong>Le serveur n'est pas pret pour une generation.</strong>
      <ul>
        {broken.map((c) => (
          <li key={c.name}>
            <b>{c.name}</b> — {c.detail}
          </li>
        ))}
      </ul>
      <button className="link-button" onClick={onRefresh}>
        Reverifier
      </button>
    </div>
  )
}

/** Compteur de silence : la seule chose visible quand plus rien n'avance. */
function Heartbeat({ job }: { job: Job }) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])

  if (!job.lastOutputAt) return null
  const wait = job.progress.waitingSeconds

  return (
    <div className={`heartbeat ${job.stalled ? 'stalled' : ''}`}>
      <span className="pulse" />
      {job.stalled ? (
        <span>
          <b>Aucune reponse depuis {since(job.lastOutputAt, now)}</b> — le process est peut-etre
          bloque. Tu peux annuler puis relancer : les scenes deja produites sont reprises sans
          nouveaux credits.
        </span>
      ) : (
        <span>
          Dernier signe de vie il y a {since(job.lastOutputAt, now)}
          {wait !== undefined && (
            <>
              {' '}
              · attente du modele : {wait}s
              {job.progress.waitingMax ? ` / ${job.progress.waitingMax}s max` : ''}
            </>
          )}
        </span>
      )}
    </div>
  )
}

/**
 * Journal des incidents. Volontairement distinct du journal brut : on y garde
 * aussi ceux dont le pipeline s'est remis, parce que trois relances Runway sur
 * la scene 7 expliquent une generation lente bien mieux qu'une barre figee.
 */
function Incidents({ incidents }: { incidents: JobIncident[] }) {
  if (incidents.length === 0) return null
  const errors = incidents.filter((i) => i.level === 'error').length
  const warns = incidents.length - errors

  return (
    <details className="incidents" open={errors > 0}>
      <summary>
        Incidents
        {errors > 0 && <span className="pill error">{errors} erreur{errors > 1 ? 's' : ''}</span>}
        {warns > 0 && <span className="pill warn">{warns} avertissement{warns > 1 ? 's' : ''}</span>}
      </summary>
      <ul>
        {[...incidents].reverse().map((inc, i) => (
          <li key={`${inc.at}-${i}`} className={inc.level}>
            <span className="incident-time">{time(inc.at)}</span>
            <span className={`pill ${inc.level}`}>{INCIDENT_LABELS[inc.kind] ?? inc.kind}</span>
            {inc.scene !== undefined && <span className="pill scene">scene {inc.scene}</span>}
            <span className="incident-message">{inc.message}</span>
            {inc.attempt !== undefined && (
              <span className="incident-attempt">
                tentative {inc.attempt}/{inc.maxAttempts}
              </span>
            )}
          </li>
        ))}
      </ul>
    </details>
  )
}

function JobDetail({ job, onCancel }: { job: Job; onCancel: (id: string) => void }) {
  const running = ACTIVE.includes(job.status)
  const { progress } = job

  return (
    <section className="panel">
      <h2>
        Job en cours <span className={`badge ${job.status}`}>{job.status}</span>
      </h2>

      {progress.idea && <p className="idea">« {progress.idea} »</p>}

      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${progress.percent}%` }} />
        <span className="progress-label">{progress.percent}%</span>
      </div>

      <p className="step">
        <strong>{STEP_LABELS[progress.step]}</strong>
        {progress.sceneCurrent && progress.sceneTotal
          ? ` — scene ${progress.sceneCurrent}/${progress.sceneTotal}`
          : ''}
        {progress.sceneStage ? ` (${progress.sceneStage})` : ''}
      </p>
      <p className="message">{progress.message}</p>

      {job.status === 'running' && <Heartbeat job={job} />}

      {job.failure ? (
        <div className="failure-card">
          <strong>{job.failure.summary}</strong>
          <p>{job.failure.hint}</p>
        </div>
      ) : (
        job.error && <div className="error-banner">{job.error}</div>
      )}

      <Incidents incidents={job.incidents ?? []} />

      {running && (
        <button className="danger" onClick={() => onCancel(job.id)}>
          Annuler
        </button>
      )}

      {job.status === 'done' && (
        <div className="result">
          <video src={api.videoUrl(job.id)} controls />
          <a className="download" href={api.downloadUrl(job.id)}>
            Telecharger la video
          </a>
        </div>
      )}

      {job.logTail.length > 0 && (
        <details className="logs">
          <summary>Journal ({job.logTail.length} lignes)</summary>
          <pre>{job.logTail.slice(-60).join('\n')}</pre>
        </details>
      )}
    </section>
  )
}

export default App
