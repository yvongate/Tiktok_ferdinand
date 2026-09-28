# syntax=docker/dockerfile:1

# Render n'a pas d'environnement Node contenant Python et FFmpeg : le pipeline
# est un script Python qui appelle FFmpeg, donc l'image doit les embarquer.
# C'est la raison d'etre de ce Dockerfile (le runtime Node natif ne suffit pas).

# --- Etape 1 : compilation TypeScript (devDependencies incluses) -----------
FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json tsconfig.build.json nest-cli.json ./
COPY src ./src
RUN npm run build

# --- Etape 2 : image finale, sans les outils de compilation ----------------
FROM node:22-slim
ENV NODE_ENV=production

# python3 : le pipeline. ffmpeg : montage + ffprobe pour mesurer les durees.
# ca-certificates : indispensable pour les appels HTTPS vers KIE.AI.
# python3-pil : le format graphique dessine ses courbes avec Pillow. Le paquet
# Debian evite un pip install (et donc une chaine de compilation) dans l'image.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      python3 python3-pil ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=build /app/dist ./dist
COPY python ./python

# Pas de PYTHON_SCRIPT_PATH ici : cette variable force UN script pour tous les
# jobs. Elle existe pour le mock de test, et la laisser en production ferait
# tourner generate.py meme sur un job "graphique" - une video Ferdinand a 0,80 $
# au lieu du graphique demande, en ignorant le sujet. Le backend choisit
# generate.py ou graphique.py d'apres le format du job.
ENV PYTHON_BIN=python3 \
    DATA_DIR=/var/data \
    PORT=3000

# On reste root volontairement : le disque persistant de Render est monte en
# root:root, et un utilisateur non privilegie ne pourrait pas y ecrire les
# videos sans etape de chown supplementaire a chaque demarrage.

EXPOSE 3000
CMD ["node", "dist/main"]
