# Ferdinand Renard — générateur de shorts « Voici pourquoi »

Application web pour lancer et suivre la génération de vidéos courtes
(finance / psychologie de l'argent, mascotte récurrente Ferdinand) depuis
n'importe où.

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
| Contenu | histoire narrée par Ferdinand | animation d'un graphique boursier réel |
| Script | `python/generate.py` | `python/graphique.py` |
| Sujets | liste validée, consommée séquentiellement | liste validée, consommée séquentiellement |
| Style visuel | 3D photoréaliste ou collage papier (voir plus bas) | rendu de courbe fixe |

Les deux listes de sujets vivent côté `python/` et sont consommées une par
une à chaque génération réussie — pas de répétition tant que la liste n'est
pas épuisée. `GET /api/generation/ideas` renvoie l'avancement des deux.

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
| `POST` | `/api/generation` | Lance un job (`format`, `mode`, `lang`, `videoModel`, `style`) |
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
(en-tête `x-api-token`, valeur `API_TOKEN`) — sans lui, n'importe qui
connaissant l'URL Render pourrait lancer des générations facturées sur la
clé KIE.AI ou supprimer des vidéos. En production, l'absence du jeton fait
échouer ces deux routes plutôt que de les laisser ouvertes.

Les routes de lecture (`GET`) restent libres : consulter l'avancement d'un
job ne coûte rien et ne modifie rien.
