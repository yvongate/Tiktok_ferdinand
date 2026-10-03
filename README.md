# Ferdinand — générateur de shorts « Pourquoi… ? »

Application web pour lancer et suivre la génération de vidéos courtes
(finance / psychologie de l'argent, mascotte récurrente Ferdinand la taupe)
depuis n'importe où.

```
back/    NestJS — API, file d'attente, orchestration du pipeline
  python/generate.py    pipeline du format narré (source de vérité)
  python/graphique.py   pipeline du format graphique boursier
  python/styles.py      familles de rendu visuel (3D / collage papier)
front/   Vite + React — tableau de bord
```

## Deux formats, deux pipelines

| | `ferdinand` | `graphique` |
|---|---|---|
| Contenu | fable chiffrée menée par Ferdinand | animation d'un graphique boursier réel |
| Script | `python/generate.py` | `python/graphique.py` |
| Sujets | liste validée, consommée séquentiellement | liste validée, consommée séquentiellement |
| Style visuel | 3D photoréaliste ou collage papier (voir plus bas) | rendu de courbe fixe |
| Sortie | 720×1280 par défaut, 1080×1920 au choix (9:16), 24 fps | 720×1280 (9:16) |

Les deux listes de sujets vivent côté `python/` et sont consommées une par
une à chaque génération réussie — pas de répétition tant que la liste n'est
pas épuisée. `GET /api/generation/ideas` renvoie l'avancement des deux.

## Le format de script

Chaque vidéo est une **fable chiffrée**, pas un exposé. Structure en sept
temps, mesurée sur 110 vidéos de chaînes comparables (voir `scriptik/`) :

| # | Étape | Rôle |
|---|---|---|
| 1 | **Question** | Le titre, mot pour mot : « Warum… ? ». Une question ouvre une boucle, une affirmation la ferme. |
| 2 | Ce que tout le monde voit | La lecture évidente, énoncée sans ironie |
| 3 | **La taupe creuse** | Elle regarde sous le contrat, les petites lignes, les vrais chiffres |
| 4 | **Le mécanisme, en chiffres** | Le cœur : l'arithmétique déroulée pas à pas, vérifiable |
| 5 | Pourquoi personne ne le voit | Trop petit pour se sentir, trop ennuyeux pour être vérifié |
| 6 | **Chute en antithèse** | Deux phrases opposées : ce que voient les autres / ce que voit la taupe |
| 7 | Appel | Court, chaleureux, sans survente |

Ferdinand n'est pas celui qui profite du mécanisme : **il le déterre et le
montre**. Il est du côté du spectateur.

Les chiffres ne sont pas un ornement, ce sont eux qui portent la révélation —
et ils doivent tomber juste. Le prompt interdit explicitement d'inventer des
statistiques : seuls les montants de la situation elle-même sont permis.

`variation.py` fait varier **la façon de dérouler le calcul** (calcul direct,
deux chemins comparés, empilement de petites sommes, chronologie) pour que
deux vidéos ne se ressemblent pas.

## Deux styles visuels pour le format ferdinand

| | `ferdinand` (défaut) | `vox` |
|---|---|---|
| Rendu | 3D photoréaliste cinématique | collage papier documentaire (découpes, trame, palette désaturée) |
| Référence image | aucune | `python/planches/vox.png`, jointe à chaque prompt pour que le personnage reste identique d'une scène à l'autre |
| Robustesse | — | planche absente ou édition échouée : repli automatique sur génération sans référence, jamais de vidéo perdue pour ça |

Les règles de prompt (palette, mise en page, interdits) sont isolées dans
`python/styles.py`, indépendantes du moteur de génération — ajouter un
troisième style n'y touche pas.

## Architecture

Le backend n'implémente pas la génération : il orchestre les scripts
Python (`generate.py` ou `graphique.py` selon le format), qui restent la
source de vérité — retries réseau, validation du script, calage vidéo/audio
par scène, tous les correctifs de robustesse y vivent.

Une génération prend 15 à 90 minutes, donc elle ne peut pas tenir dans
une requête HTTP :

1. `POST /api/generation` dépose un job dans une file et répond immédiatement
2. Un worker interne lance le script Python en sous-processus
3. Sa sortie est parsée ligne par ligne en progression structurée
   (étape, scène n/N, sous-étape voix/image/vidéo, pourcentage)
4. Le front suit en direct via SSE (`GET /api/generation/:id/events`)
5. La vidéo finale est servie avec support des requêtes `Range`

La file est séquentielle et interne (pas de Redis/BullMQ) : pour un usage
mono-utilisateur c'est suffisant, et ça évite un service supplémentaire à
héberger. Toute la logique est isolée dans `jobs.service.ts` — passer à
BullMQ plus tard ne toucherait que ce fichier.

## Visibilité sur les erreurs

Une génération dure des dizaines de minutes et dépend d'API externes. Plusieurs
mécanismes évitent d'attendre sans savoir ce qui se passe :

**1. Pré-vol** — `GET /api/health` vérifie la clé API, le jeton d'écriture,
Python, FFmpeg, FFprobe, les scripts des deux formats, la planche de style et
le dossier de données. Le front affiche un bandeau avant de lancer quoi
que ce soit ; une clé ou une planche manquante ne se découvre plus au milieu
d'un job, après des appels déjà facturés.

**2. Journal des incidents** — chaque ligne anormale d'un script est classée
(`network`, `http`, `api-task`, `download`, `validation`, `timeout`, `scene`,
`stall`, `fatal`), horodatée, rattachée à sa scène et à son compteur de
tentatives. Les incidents dont le pipeline s'est remis sont conservés :
c'est ce qui distingue « ça a pris 40 min » de « ça a pris 40 min parce que
Runway a échoué 3 fois sur la scène 7 ».

**3. Battement de cœur + watchdog** — `wait_for_result()` émet une ligne toutes
les ~24 s pendant les attentes longues (sinon la sortie est muette jusqu'à
10 min pendant la génération vidéo). Le backend suit ce battement : plus rien
pendant 3 minutes et le job est marqué `stalled`, avec un incident. L'interface
affiche en continu le délai depuis le dernier signe de vie.

**4. Diagnostic d'échec** — `diagnose.ts` traduit un code de sortie 1 en
cause lisible et en action : clé absente, clé refusée, crédits épuisés, quota
atteint, FFmpeg ou Python manquant, réseau. Le front l'affiche à la place du
message technique.

**5. Repli plutôt qu'échec sec** — quand un élément annexe manque (planche de
style, référence d'édition image), le script le signale comme incident et
continue en mode dégradé plutôt que de perdre toute la génération.

### Tester ces chemins d'erreur

`MOCK_FAULTS` rejoue des pannes dans le mock, sans aucun appel API :

```bash
MOCK_FAULTS=retries PYTHON_SCRIPT_PATH=./python/_mock_generate.py npm run start:dev
```

| Valeur | Rejoue |
|---|---|
| `retries` | timeout réseau, rejet de sortie, tâche fournisseur échouée, téléchargement coupé — le job réussit quand même |
| `fatal` | arrêt après 3 scripts invalides |
| `quota` | HTTP 429 puis abandon (diagnostic `quota`) |
| `stall` | 4 min de silence — déclenche le watchdog |

## Résolution : 720p ou 1080p

Choisie dans l'interface (format Ferdinand uniquement), transmise au modèle
vidéo **et** imposée à tout le montage — les deux doivent concorder, sinon le
concat final en `-c copy` refuse de coller des segments de tailles
différentes.

**720p par défaut**, parce que le 1080p coûte **2,5× plus cher** chez le
fournisseur (Runway image-to-video 5 s : $0,15 contre $0,06). Sur une vidéo
de 12 scènes — le cas courant en mode 60s — c'est $1,80 contre $0,72.

Les clips intermédiaires sont ré-encodés en **crf 18**, plus fin que la passe
finale (crf 20) : les pertes se cumulent, et ce qu'un premier encodage écrase
ne revient pas. Sans ce réglage, libx264 appliquait son défaut (crf 23) juste
après le téléchargement, gâchant une partie de la résolution payée.

Changer de résolution sur un même sujet **ne réutilise pas** le cache des
scènes : les clips doivent être regénérés à la bonne taille.

## Nettoyage des métadonnées IA

Après le montage final, `python/ai_metadata.py` scanne la vidéo (tags
ffprobe + boîtes MP4) puis nettoie le conteneur **systématiquement**, en une
passe `ffmpeg -c copy` : pas de ré-encodage, pixels intacts, environ une
seconde.

Systématique et non conditionnel, pour deux raisons :

- **`+faststart`** place l'index (`moov`) en tête de fichier, si bien que la
  lecture démarre sans attendre le téléchargement complet — utile à l'upload
  et en streaming. Ne nettoyer qu'en cas de marqueur détecté privait toutes
  les vidéos de ce gain, puisqu'on n'en trouve jamais.
- Ça retire aussi les **tags d'encodeur résiduels** (versions de FFmpeg) et
  tout marqueur de provenance IA qui serait présent (C2PA, « AI-generated »).

En pratique les remux successifs du montage ont déjà fait disparaître ce que
Runway ou Seedance auraient pu poser : l'inspection d'une vraie sortie ne
trouve aucun marqueur. Le scan reste un filet de sécurité, et signale tout
marqueur qui survivrait au nettoyage.

Non bloquant : un échec garde la vidéo d'origine plutôt que de perdre la
génération.

### Régénération des pixels (optionnelle, désactivée par défaut)

`python/synthid_remove.py` envoie la vidéo finale à un service GPU externe
qui re-synthétise chaque image à travers un VAE : les pixels de sortie ne
sont plus ceux du modèle vidéo, ce qui perturbe tout signal invisible qui y
serait caché. Perturbation **générique** — le code d'origine visait SynthID
(Google), le mécanisme ne cible aucun filigrane en particulier.

Activation : `SYNTHID_REMOVE=1` **et** `SYNTHID_REMOTE_URL` (sans service
configuré, l'étape est simplement ignorée). Le service expose `/submit`,
`/status/:id`, `/result/:id` — voir `back/modal/app.py` du projet
[remove-ai-matadata](https://github.com/yvongate/remove-ai-matadata).

| Variable | Rôle |
|---|---|
| `SYNTHID_REMOVE` | `1` pour activer l'étape |
| `SYNTHID_REMOTE_URL` | URL du service GPU |
| `SYNTHID_REMOTE_KEY` | clé envoyée en `x-api-key` |
| `SYNTHID_LONG_SIDE` | défaut : le grand côté réel de la vidéo (pas d'upscale inutile) |
| `SYNTHID_NOISE_STD` | défaut `0.15` (valeur calibrée en amont, à 512 px) |
| `SYNTHID_REMOTE_TIMEOUT_S` | défaut `3600` |

Trois réserves avant d'activer :

- **Les sous-titres sont incrustés avant cette étape** : un VAE reconstruit
  mal le texte fin, attendre un rendu plus mou sur les sous-titres animés.
- **L'efficacité est invérifiable** : aucun fournisseur ne publie de
  détecteur, ni Google, ni ByteDance, ni Runway. Ni preuve que ça marche,
  ni preuve que c'est nécessaire.
- **Le coût GPU est réel**, facturé à la seconde, en plus d'un aller-retour
  réseau de la taille de la vidéo.

Non bloquant comme le reste du pipeline : service injoignable, délai dépassé
ou erreur GPU laissent la vidéo d'origine intacte.

## Développement

```bash
# Backend (port 3000)
cd back && npm install && npm run start:dev

# Frontend (port 5173, proxy /api -> 3000)
cd front && npm install && npm run dev
```

Copier `back/.env.example` vers `back/.env` et renseigner `KIE_API_KEY`.

### Tester sans dépenser de crédits

`back/python/_mock_generate.py` reproduit la sortie du vrai script en
quelques secondes, sans aucun appel API :

```bash
PYTHON_SCRIPT_PATH=./python/_mock_generate.py npm run start:dev
```

## API

| Méthode | Route | Rôle |
|---|---|---|
| `POST` | `/api/generation` | Lance un job (`format`, `mode`, `lang`, `videoModel`, `style`, `quality`) |
| `GET` | `/api/generation` | Historique des jobs |
| `GET` | `/api/generation/:id` | État d'un job |
| `GET` | `/api/generation/:id/events` | Suivi live (SSE) |
| `GET` | `/api/generation/:id/video?download=1` | Vidéo finale (support `Range`, `download` force le téléchargement) |
| `DELETE` | `/api/generation/:id` | Annule si le job tourne encore, **supprime** (fichiers compris) s'il est terminé |
| `GET` | `/api/generation/ideas` | Avancement des listes de sujets, par format |
| `GET` | `/api/health` | Pré-vol : clé API, jeton, Python, FFmpeg, scripts, planche de style, disque |

`POST` et `DELETE` exigent le jeton d'écriture (voir section Sécurité).

## Hébergement — front sur Vercel, back sur Render

Les deux sont sur des domaines différents : c'est ce qui impose `VITE_API_BASE`
côté front et `FRONT_ORIGIN` côté back. Déployer le backend **en premier** :
son URL est nécessaire pour construire le front.

### 1. Backend sur Render

Le `render.yaml` à la racine décrit le service ; l'importer via
**New > Blueprint**. En configuration manuelle : runtime **Docker**,
Dockerfile `./back/Dockerfile`, contexte `./back`.

Variables à renseigner dans le tableau de bord :

| Variable | Valeur |
|---|---|
| `KIE_API_KEY` | ta clé KIE.AI |
| `FRONT_ORIGIN` | l'URL Vercel, sans slash final (plusieurs séparées par des virgules) |
| `API_TOKEN` | jeton d'écriture — **obligatoire en production**, voir Sécurité |
| `WATERMARK` | pseudo incrusté en filigrane mobile (ex. `@darum.finanzen`) ; vide = aucun filigrane |

`DATA_DIR`, `PYTHON_BIN` et `PYTHON_SCRIPT_PATH` sont déjà posés par l'image.

> **Ne pas prendre le plan gratuit.** Une instance gratuite s'endort après
> ~15 min sans requête entrante. Une génération dure 15 à 90 min : fermer
> l'onglet suffirait à tuer le job en cours, après des appels déjà facturés.

> **Le disque doit être persistant.** Sans le bloc `disk` du `render.yaml`, le
> système de fichiers est éphémère et les vidéos disparaissent à chaque
> redéploiement *et* à chaque redémarrage.

### 2. Frontend sur Vercel

**Root Directory : `front`** (sinon Vercel construit la racine et ne trouve
rien). Le framework Vite est détecté automatiquement.

Deux variables, dans *Settings > Environment Variables* :

```
VITE_API_BASE  = https://ton-service.onrender.com
VITE_API_TOKEN = la même valeur que API_TOKEN côté Render
```

> **Vite fige ces valeurs au moment du build.** Les modifier dans Vercel ne
> change rien tant qu'un nouveau déploiement n'a pas été lancé — et les deux
> jetons (front/back) doivent rester identiques en permanence, sinon toutes
> les générations sont refusées.

### 3. Boucler le CORS

Une fois l'URL Vercel connue, revenir sur Render et mettre `FRONT_ORIGIN` à
cette URL. Sans ça le navigateur bloque tous les appels, et l'interface reste
vide sans message explicite.

Vercel crée aussi une URL par déploiement de préversion : les ajouter à
`FRONT_ORIGIN` séparées par des virgules si tu veux qu'elles fonctionnent.

### Vérifier

```bash
curl https://ton-service.onrender.com/api/health
```

Doit répondre `ok: true` avec Python, FFmpeg, FFprobe, la clé API, le jeton
et la planche de style au vert. Sinon l'interface affichera le bandeau rouge
de pré-vol.

### Sécurité

`POST /api/generation` et `DELETE /api/generation/:id` exigent un jeton
(en-tête `x-ferdinand-token`, valeur `API_TOKEN`) — sans lui, n'importe qui
connaissant l'URL Render pourrait lancer des générations facturées sur la
clé KIE.AI ou supprimer des vidéos. En production, l'absence du jeton fait
échouer ces deux routes plutôt que de les laisser ouvertes.

Les routes de lecture (`GET`) restent libres : consulter l'avancement d'un
job ne coûte rien et ne modifie rien.

## Crédits

`ai_metadata.py` et le client GPU de `synthid_remove.py` sont des ports
originaux (stdlib pure) de la logique de
[remove-ai-matadata](https://github.com/yvongate/remove-ai-matadata). Le code
VAE sous licence Apache-2.0 n'est **pas** embarqué ici : il vit côté service
GPU, ce qui évite de traîner 70 Ko de code tiers inexécutable dans ce dépôt.
