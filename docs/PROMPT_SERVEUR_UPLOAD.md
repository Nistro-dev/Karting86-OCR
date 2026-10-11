# Mission

Crée un **serveur d'upload de fichiers** minimal et fonctionnel, à déployer immédiatement sur un serveur dédié Linux avec Docker.

N'importe qui avec la clé API peut uploader des fichiers de n'importe quelle taille. Les fichiers sont stockés sur le disque du serveur.

# Fonctionnalités

1. `POST /upload` — Upload un ou plusieurs fichiers (multipart/form-data), protégé par clé API (header `X-API-Key`)
2. `GET /files` — Liste tous les fichiers uploadés (nom, taille, date)
3. `GET /files/{filename}` — Télécharger un fichier
4. `GET /status` — Health check (espace disque restant, nombre de fichiers)

# Contraintes

- **Pas de limite de taille** sur les fichiers (ou au moins 2 Go)
- Fichiers stockés dans un dossier `/data/uploads/` (volume Docker)
- Clé API configurable via variable d'environnement `API_KEY`
- Le serveur doit démarrer en **moins de 2 minutes** (docker compose up)
- Log chaque upload en console (nom fichier, taille, IP)

# Stack

- Python + FastAPI + uvicorn
- Docker + docker-compose
- Pas de base de données, juste le filesystem

# Livrables

Crée tous les fichiers dans un dossier `upload-server/` :

1. `upload-server/server.py` — Le serveur FastAPI
2. `upload-server/requirements.txt` — fastapi, uvicorn, python-multipart
3. `upload-server/Dockerfile`
4. `upload-server/docker-compose.yml` — avec volume pour `/data/uploads/` et variable `API_KEY`
5. Un `README.md` avec les 3 commandes pour déployer

Le serveur doit écouter sur le port **8899** en interne. Il sera accessible via `https://claudepistekarting.codeforgestudio.fr` (le reverse proxy/SSL est déjà géré côté serveur, toi tu écoutes juste sur le port 8899).

Déploie-le immédiatement après l'avoir créé : lance `docker compose up -d --build`.

Génère une clé API aléatoire et affiche-la à la fin.
