import type { JobFailure, JobIncident } from './job.types';

/**
 * Traduit un echec technique en cause comprehensible.
 *
 * Sans ca, l'interface n'a qu'un "code de sortie 1" a montrer : on sait que
 * c'est casse, jamais pourquoi, et il faut aller lire les logs du serveur.
 * Chaque regle correspond a une panne reellement rencontrable avec KIE.AI,
 * FFmpeg ou l'environnement d'hebergement.
 */

interface Rule {
  kind: JobFailure['kind'];
  /** Teste sur l'ensemble des logs, en minuscules. */
  match: RegExp;
  summary: string;
  hint: string;
}

const RULES: Rule[] = [
  {
    kind: 'api-key-missing',
    match: /cle api introuvable|kie_api_key/i,
    summary: "La cle API KIE.AI n'est pas configuree",
    hint: "Renseigner la variable d'environnement KIE_API_KEY sur le serveur, puis relancer.",
  },
  {
    kind: 'api-key-rejected',
    match: /http (401|403)\b|unauthorized|invalid api key|forbidden/i,
    summary: 'KIE.AI a refuse la cle API',
    hint: "La cle est presente mais rejetee : verifier qu'elle est complete, active, et qu'elle n'a pas ete revoquee.",
  },
  {
    kind: 'credits',
    match: /insufficient|no credit|balance|solde insuffisant|not enough/i,
    summary: 'Credits KIE.AI insuffisants',
    hint: 'Recharger le compte KIE.AI. Les scenes deja produites sont conservees : relancer reprendra depuis le cache.',
  },
  {
    kind: 'quota',
    match: /http 429\b|rate limit|too many requests|quota/i,
    summary: 'Limite de debit atteinte chez KIE.AI',
    hint: 'Attendre quelques minutes avant de relancer. Une seule generation a la fois reduit ce risque.',
  },
  {
    kind: 'ffmpeg-missing',
    match: /ffmpeg.*(not found|introuvable|enoent)|'ffmpeg' n'est pas reconnu/i,
    summary: "FFmpeg n'est pas installe sur le serveur",
    hint: "Le montage final a besoin de FFmpeg dans l'image de deploiement (voir le Dockerfile).",
  },
  {
    kind: 'python-missing',
    match: /erreur de lancement du process python|spawn .* enoent/i,
    summary: 'Python est introuvable sur le serveur',
    hint: 'Verifier PYTHON_BIN (souvent "python3" sous Linux/Docker, "python" sous Windows).',
  },
  {
    kind: 'network',
    match: /erreur reseau|timeout apres|getaddrinfo|econnreset|remotedisconnected/i,
    summary: 'Le reseau a lache pendant les appels API',
    hint: 'Le pipeline retente deja plusieurs fois ; si ca persiste, verifier la connexion sortante du serveur.',
  },
];

/**
 * Cherche une cause connue dans les logs. Les incidents sont pris en compte
 * en priorite : ce sont deja les lignes anormales, donc moins de bruit qu'un
 * scan du journal complet.
 */
export function diagnose(
  logTail: string[],
  incidents: JobIncident[],
  producedVideo: boolean,
  exitedCleanly: boolean,
): JobFailure {
  const haystack = [...incidents.map((i) => i.message), ...logTail].join('\n');

  for (const rule of RULES) {
    if (rule.match.test(haystack)) {
      return { kind: rule.kind, summary: rule.summary, hint: rule.hint };
    }
  }

  if (exitedCleanly && !producedVideo) {
    return {
      kind: 'no-video',
      summary: "Le script s'est termine sans produire de video",
      hint: "Une etape a abandonne sans planter (souvent une scene impossible a generer). Le journal ci-dessous indique laquelle.",
    };
  }

  return {
    kind: 'unknown',
    summary: 'Echec sans cause identifiee',
    hint: 'Ouvrir le journal ci-dessous : la derniere ligne avant l\'arret indique generalement l\'etape fautive.',
  };
}
