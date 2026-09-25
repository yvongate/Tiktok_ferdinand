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
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 ffmpeg ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev && npm cache clean --force

COPY --from=build /app/dist ./dist
COPY python ./python

# Le script Python n'a aucune dependance externe (stdlib uniquement) : pas de
# pip install, donc rien a maintenir de ce cote.

ENV PYTHON_BIN=python3 \
    PYTHON_SCRIPT_PATH=/app/python/generate.py \
    DATA_DIR=/var/data \
    PORT=3000

# On reste root volontairement : le disque persistant de Render est monte en
# root:root, et un utilisateur non privilegie ne pourrait pas y ecrire les
# videos sans etape de chown supplementaire a chaque demarrage.

EXPOSE 3000
CMD ["node", "dist/main"]
