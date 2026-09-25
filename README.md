# Ferdinand Renard — générateur de shorts « Voici pourquoi »

Application web pour lancer et suivre la génération de vidéos courtes
(finance / psychologie de l'argent, rendu 3D photoréaliste, mascotte
récurrente Ferdinand) depuis n'importe où.

```
back/    NestJS — API, file d'attente, orchestration du pipeline
  python/generate.py   le pipeline de génération (source de vérité)
front/   Vite + React — tableau de bord
```

## Architecture

Le backend **n'implémente pas** la génération : il orchestre le script
Python `back/python/generate.py`, qui reste la source de vérité (tous les
correctifs de robustesse accumulés — retries réseau, validation du script,
calage vidéo/audio par scène — y vivent).

Une génération prend **15 à 90 minutes**, donc elle ne peut pas tenir dans
une requête HTTP :

1. `POST /api/generation` dépose un job dans une file et répond immédiatement
2. Un worker interne lance `generate.py` en sous-processus
3. Sa sortie est parsée ligne par ligne en progression structurée
   (étape, scène n/N, sous-étape voix/image/vidéo, pourcentage)
4. Le front suit en direct via **SSE** (`GET /api/generation/:id/events`)
5. La vidéo finale est servie avec support des requêtes `Range`

La file est **séquentielle et interne** (pas de Redis/BullMQ) : pour un usage
mono-utilisateur c'est suffisant, et ça évite un service supplémentaire à
héberger. Toute la logique est isolée dans `jobs.service.ts` — passer à
BullMQ plus tard ne toucherait que ce fichier.

## Visibilité sur les erreurs

Une génération dure des dizaines de minutes et dépend d'API externes. Quatre
mécanismes évitent d'attendre sans savoir ce qui se passe :

**1. Pré-vol** — `GET /api/health` vérifie la clé API, Python, FFmpeg, FFprobe,
le script et le dossier de données. Le front affiche un bandeau **avant** de
lancer quoi que ce soit ; une clé manquante ne se découvre plus au milieu d'un
job, après des appels déjà facturés.

**2. Journal des incidents** — chaque ligne anormale de `generate.py` est
classée (`network`, `http`, `api-task`, `download`, `validation`, `timeout`,
`scene`, `stall`, `fatal`), horodatée, rattachée à sa scène et à son compteur
de tentatives. Les incidents dont le pipeline s'est **remis** sont conservés :
c'est ce qui distingue « ça a pris 40 min » de « ça a pris 40 min parce que
Runway a échoué 3 fois sur la scène 7 ».

**3. Battement de cœur + watchdog** — `wait_for_result()` émet une ligne toutes
les ~24 s pendant les attentes longues (sinon la sortie est muette jusqu'à
10 min pendant la génération vidéo). Le backend suit ce battement : plus rien
pendant 3 minutes et le job est marqué `stalled`, avec un incident. L'interface
affiche en continu le délai depuis le dernier signe de vie.

**4. Diagnostic d'échec** — `diagnose.ts` traduit un « code de sortie 1 » en
cause lisible et en action : clé absente, clé refusée, crédits épuisés, quota
atteint, FFmpeg ou Python manquant, réseau. Le front l'affiche à la place du
message technique.

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
| `POST` | `/api/generation` | Lance un job (`mode`, `lang`, `videoModel`) |
| `GET` | `/api/generation` | Historique des jobs |
| `GET` | `/api/generation/:id` | État d'un job |
| `GET` | `/api/generation/:id/events` | Suivi live (SSE) |
| `GET` | `/api/generation/:id/video` | Vidéo finale (support `Range`) |
| `DELETE` | `/api/generation/:id` | Annule un job |
| `GET` | `/api/health` | Pré-vol : clé API, Python, FFmpeg, disque |

## Hébergement (Render)

L'image Docker doit contenir **Node, Python et FFmpeg**. Points d'attention :

- Déployer le backend en **Background Worker** ou Web Service avec un
  timeout large — les jobs durent bien plus qu'une requête HTTP classique.
- Le disque de Render est **éphémère** : monter un disque persistant sur
  `DATA_DIR`, ou pousser les vidéos vers un stockage objet (S3, R2), sinon
  elles disparaissent à chaque redéploiement.
- Renseigner `KIE_API_KEY`, `FRONT_ORIGIN` et `PYTHON_BIN=python3`.
