import { useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import {
  api,
  INCIDENT_LABELS,
  STEP_LABELS,
  FORMAT_LABELS,
  STYLE_LABELS,
  QUALITY_LABELS,
  titreIdee,
  type Format,
  type Style,
  type Quality,
  type HealthReport,
  type IdeasProgress,
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
    format: 'ferdinand',
    mode: '60s',
    lang: 'de',
    videoModel: 'runway',
    style: 'vox',
    quality: '720p',
  })
  const [jobs, setJobs] = useState<Job[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [launching, setLaunching] = useState(false)
  const [health, setHealth] = useState<HealthReport | null>(null)
  const [ideas, setIdeas] = useState<IdeasProgress[]>([])
  const unsubscribe = useRef<(() => void) | null>(null)

  const upsert = useCallback((job: Job) => {
    setJobs((prev) => {
      const i = prev.findIndex((j) => j.id === job.id)
      if (i === -1) return [job, ...prev]
      const next = [...prev]
      // L'historique arrive allege (logTail et incidents vides, voir le
      // controleur) : l'y fusionner tel quel effacerait le detail deja recu
      // par le flux live du job affiche.
      const ancien = prev[i]
      next[i] = {
        ...job,
        logTail: job.logTail?.length ? job.logTail : ancien.logTail,
        incidents: job.incidents?.length ? job.incidents : ancien.incidents,
      }
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
    api.ideas().then(setIdeas).catch(() => setIdeas([]))
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

  // L'idee n'est consommee qu'a la reussite du job : on relit le compteur
  // des qu'un job quitte l'etat actif, sinon la barre reste en retard.
  const activeCount = jobs.filter((j) => ACTIVE.includes(j.status)).length
  useEffect(() => {
    api.ideas().then(setIdeas).catch(() => {})
  }, [activeCount])

  /**
   * Rafraichissement de l'historique tant qu'un job tourne.
   *
   * Le flux live ne suit que le job SELECTIONNE. Il suffisait donc de cliquer
   * sur une autre ligne pendant une generation pour que celle-ci reste
   * « running » a l'ecran jusqu'a la fin des temps : le bouton affichait
   * « Generation en cours… » definitivement et la barre d'idees ne bougeait
   * plus, un rechargement de page etant le seul remede.
   */
  useEffect(() => {
    if (activeCount === 0) return
    const t = setInterval(() => {
      api
        .list()
        .then((liste) => liste.forEach(upsert))
        .catch(() => {})
    }, 5000)
    return () => clearInterval(t)
  }, [activeCount, upsert])

  const selected = jobs.find((j) => j.id === selectedId) ?? null

  const launch = async () => {
    setError(null)
    setLaunching(true)
    try {
      const job = await api.create(params)
      upsert(job)
      setSelectedId(job.id)
      api.ideas().then(setIdeas).catch(() => {})
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setLaunching(false)
    }
  }

  // Un job actif s'annule ; un job termine disparait pour de bon, fichiers
  // compris. Meme geste, meme bouton, effet adapte a l'etat.
  const cancelOrDelete = async (id: string) => {
    try {
      const res = await api.cancelOrDelete(id)
      if ('freed' in res) {
        setJobs((prev) => prev.filter((j) => j.id !== id))
        setSelectedId((cur) => (cur === id ? null : cur))
      } else {
        upsert(res)
      }
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const hasActive = activeCount > 0
  // L'epuisement se juge sur la liste DU FORMAT choisi : Ferdinand peut
  // etre termine alors qu'il reste des sujets graphiques.
  const courant = ideas.find((i) => i.format === params.format) ?? null
  const exhausted = courant !== null && courant.total > 0 && courant.remaining === 0

  return (
    <div className="app">
      <header>
        <h1>Ferdinand Renard</h1>
        {/* Le format garde sa structure, seule l'accroche change selon la
            langue : « Warum » (de), « Pourquoi » (fr), « Why » (en). */}
        <p className="subtitle">Generateur de shorts explicatifs</p>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <HealthBanner health={health} onRefresh={() => api.health().then(setHealth).catch(() => {})} />

      {ideas.map((i) => (
        <IdeasPanel key={i.format} ideas={i} actif={i.format === params.format} />
      ))}

      <section className="panel">
        <h2>Nouvelle video</h2>
        <div className="form">
          <label>
            Type de video
            <select
              value={params.format}
              onChange={(e) =>
                setParams({ ...params, format: e.target.value as Format })
              }
            >
              {(Object.keys(FORMAT_LABELS) as Format[]).map((f) => (
                <option key={f} value={f}>
                  {FORMAT_LABELS[f]}
                </option>
              ))}
            </select>
          </label>

          {/* Ampleur narrative et modele video n'existent que pour Ferdinand :
              graphique.py les ignore. Les laisser affiches donnait deux
              reglages sans le moindre effet. */}
          {params.format === 'ferdinand' && (
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
          )}

          <label>
            Langue
            <select
              value={params.lang}
              onChange={(e) => setParams({ ...params, lang: e.target.value as JobParams['lang'] })}
            >
              <option value="de">Allemand</option>
              <option value="fr">Francais</option>
              <option value="en">Anglais</option>
            </select>
          </label>

          {/* Le style ne concerne que Ferdinand : graphique.py dessine ses
              courbes lui-meme et ignore la famille visuelle. */}
          {params.format === 'ferdinand' && (
            <label>
              Style visuel
              <select
                value={params.style}
                onChange={(e) => setParams({ ...params, style: e.target.value as Style })}
              >
                {(Object.keys(STYLE_LABELS) as Style[]).map((s) => (
                  <option key={s} value={s}>
                    {STYLE_LABELS[s]}
                  </option>
                ))}
              </select>
            </label>
          )}

          {params.format === 'ferdinand' && (
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
          )}

          {/* Comme le style : le format graphique dessine ses images
              localement, la resolution du modele video ne le concerne pas. */}
          {params.format === 'ferdinand' && (
            <label>
              Resolution
              <select
                value={params.quality}
                onChange={(e) => setParams({ ...params, quality: e.target.value as Quality })}
              >
                {(Object.keys(QUALITY_LABELS) as Quality[]).map((q) => (
                  <option key={q} value={q}>
                    {QUALITY_LABELS[q]}
                  </option>
                ))}
              </select>
            </label>
          )}

          <button onClick={launch} disabled={launching || hasActive || exhausted}>
            {launching
              ? 'Lancement...'
              : hasActive
                ? 'Generation en cours...'
                : exhausted
                  ? 'Liste d’idees epuisee'
                  : 'Lancer la generation'}
          </button>
        </div>
        {hasActive && (
          <p className="hint">
            Une seule generation a la fois — la suivante sera mise en file d'attente.
          </p>
        )}
      </section>

      {selected && <JobDetail job={selected} onCancel={cancelOrDelete} />}

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
                {job.degraded && <span className="pill error">incomplete</span>}
              </span>
              <span className="history-meta">
                <span className="pill format">{job.params.format ?? 'ferdinand'}</span>
                {job.params.format === 'graphique'
                  ? ` ${job.params.lang}`
                  : ` ${job.params.mode} · ${job.params.lang} · ${job.params.videoModel}` +
                    // Jobs d'avant l'option : ni 720p ni 1080p enregistres.
                    (job.params.quality ? ` · ${job.params.quality}` : '')}
                {job.params.style === 'vox' && (
                  <span className="pill format">collage</span>
                )}
                {/* incidentCount vient de l'historique allege ; incidents du
                    flux SSE, qui remplace l'entree par le job complet. */}
                {incidentTotal(job) > 0 && (
                  <span className="pill warn">{incidentTotal(job)} incident(s)</span>
                )}
              </span>
              <span className="history-date">
                {new Date(job.createdAt).toLocaleString('fr-FR')}
              </span>
              {/* stopPropagation : sans ca, le clic selectionnerait aussi la
                  ligne avant de la supprimer. */}
              <button
                className="history-delete"
                title={
                  ACTIVE.includes(job.status)
                    ? 'Annuler cette generation'
                    : 'Supprimer definitivement (libere le disque)'
                }
                onClick={(e) => {
                  e.stopPropagation()
                  cancelOrDelete(job.id)
                }}
              >
                {ACTIVE.includes(job.status) ? '■' : '×'}
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}

/**
 * Avancement dans la liste d'idees validees a la main.
 *
 * Affiche aussi le prochain titre : c'est lui qui partira au clic suivant,
 * et le voir AVANT de lancer evite de decouvrir apres coup qu'on a produit
 * une video dont le sujet ne convenait pas.
 */
function IdeasPanel({ ideas, actif }: { ideas: IdeasProgress; actif: boolean }) {
  if (ideas.total === 0) return null
  const done = ideas.remaining === 0

  // Le panneau du format NON selectionne reste visible mais en retrait :
  // on doit pouvoir verifier son avancement sans le confondre avec celui
  // qui partira au prochain clic.
  return (
    <section className={`panel ideas-panel ${actif ? '' : 'inactif'}`}>
      <h2>
        {FORMAT_LABELS[ideas.format]}
        <span className="ideas-count">
          {ideas.used} / {ideas.total}
        </span>
      </h2>

      <div className="progress-bar">
        <div className="progress-fill" style={{ width: `${ideas.percent}%` }} />
        {/* Le pourcentage affichait "0%" des la premiere idee consommee
            (1/300 arrondi a 0) : vrai, mais contredit le "1 / 300" juste
            au-dessus. Le nombre restant ne ment jamais. */}
        <span className="progress-label">{ideas.remaining} restantes</span>
      </div>

      {done ? (
        <div className="failure-card">
          <strong>Les {ideas.total} entrees ont ete utilisees.</strong>
          <p>
            Regenere la liste, valide-la, puis
            redeploie. Le bouton reste desactive d'ici la — plutot que de
            reboucler en silence sur des sujets deja publies.
          </p>
        </div>
      ) : (
        ideas.next && (
          <div className="next-idea">
            <span className="next-label">Prochaine ({ideas.next.n})</span>
            <p className="next-de">{titreIdee(ideas.next)}</p>
            <p className="next-fr">
              {ideas.next.fr ??
                `${ideas.next.histoire} — 100 € deviennent ${ideas.next.final} €`}
            </p>
          </div>
        )
      )}
    </section>
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

      {/* Une video peut etre livree ET amputee. Sans cet encart, elle se
          presentait exactement comme une reussite complete : c'est ainsi
          qu'une video de 58s au lieu de 75s est passee inapercue. */}
      {job.degraded && (
        <div className="failure-card degraded">
          <strong>
            Video incomplete : {progress.scenesDone}/{progress.scenesPlanned} scenes
          </strong>
          <p>
            Des scenes ont echoue et le montage a continue sans elles — la video est plus
            courte que prevu. Le sujet n'a PAS ete consomme et les scenes deja payees sont
            conservees : relancer ne refacturera que les scenes manquantes. Le detail est
            dans les incidents ci-dessous.
          </p>
        </div>
      )}

      <Incidents incidents={job.incidents ?? []} />

      <button className="danger" onClick={() => onCancel(job.id)}>
        {running ? 'Annuler' : 'Supprimer (libere le disque)'}
      </button>

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
