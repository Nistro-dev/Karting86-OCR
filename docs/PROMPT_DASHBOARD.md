# Mission

Crée un dashboard web temps réel pour une piste de karting (Karting86). Le site affiche en direct la progression des sessions : classement, temps au tour, temps restant, tours effectués. Les données viennent de la base Firebird d'Apex Timing (logiciel GoKarts).

# Source de données : Firebird

## Connexion
- Base Firebird 5.0, fichier quotidien : `C:\ApexTiming\Data\DAY<YYYYMMDD>.GO`
- Host: `localhost:3050`, user: `SYSDBA`, password: `masterkey`
- Transactions READ-ONLY uniquement — ne jamais écrire dans la BDD
- Librairie Python : `firebird-driver`
- Le fichier change chaque jour → détecter automatiquement le bon fichier
- Paramètres globaux (durées par modèle) dans `CENTER.GO`

## Timestamps
Tous les timestamps Firebird sont en **microsecondes depuis 1899-12-30** (format Delphi TDateTime).
Conversion vers Python : `unix_ts = (firebird_us - 59_926_435_200_000_000) / 1_000_000`

## Tables

### T1_SESSIONS_V8 — Sessions
| Colonne | Type | Description |
|---------|------|-------------|
| CIDX | INT | Index session (1-50) |
| CSTATUS | INT | Flags : bits 0x10=démarrée, 0x01=active, 0x20=terminée, 0x100=durée manuelle, 0x04=pause |
| CSTARTTIME | BIGINT | Début (µs Delphi) |
| CPAUSETIME | BIGINT | En pause: début pause. Après reprise: cumul pauses (µs) |
| CFINISHTIME | BIGINT | Fin (µs), 0 si pas terminée |
| CDURATION | BIGINT | Durée prévue (µs). Ex: 600 000 000 = 10 min |
| CLAPS | INT | Tours total (0 = session chrono/temps) |
| CKART | INT | ID modèle de kart |
| CNAME | VARCHAR | Nom de la session |

### T1_S{n}_RC — Passages karts (n = CIDX de la session)
| Colonne | Type | Description |
|---------|------|-------------|
| CTI | BIGINT | Timestamp passage (µs Delphi) |
| CST | INT | Statut (65282 = départ, ignorer pour les tours) |
| CKID | INT | Numéro de kart |
| CDID | INT | ID pilote |
| CTLP | INT | Numéro de tour pour ce kart |
| CTTI | BIGINT | Temps total session ce kart (µs) |
| CLP | BIGINT | Temps au tour (µs) |

### TTRACKS_CASES_V20 — Durées auto par modèle (dans CENTER.GO)
| Colonne | Description |
|---------|-------------|
| CKART_MODEL | Modèle de kart |
| CVALUE | Durée en µs |
Requête : `SELECT CKART_MODEL, CVALUE FROM TTRACKS_CASES_V20 WHERE CTRACK=1 AND CFIELD=11 AND CDAY_OF_WEEK=0 AND CVALUE>0`

## Requêtes SQL clés

```sql
-- Sessions démarrées
SELECT CIDX, CSTATUS, CSTARTTIME, CPAUSETIME, CFINISHTIME,
       CDURATION, CLAPS, CKART, CNAME
FROM T1_SESSIONS_V8 WHERE CSTARTTIME > 0

-- Classement live (session n) — exclure CST=65282 (ligne départ)
SELECT CKID, CDID, max(CTLP) as tours, max(CTTI) as temps_total,
       min(CLP) as meilleur_tour
FROM T1_S{n}_RC WHERE CST <> 65282
GROUP BY CKID, CDID
ORDER BY tours DESC, temps_total ASC

-- Tous les tours d'un kart
SELECT CTLP, CLP, CTTI FROM T1_S{n}_RC
WHERE CKID = {kart_id} AND CST <> 65282 ORDER BY CTLP
```

## Logique métier

```python
# Session active = flags 0x01 (active) ET 0x10 (démarrée) à True
def is_active(status): return bool(status & 0x01) and bool(status & 0x10)
def is_paused(status): return bool(status & 0x04)
def is_finished(status): return bool(status & 0x20)
def is_manual_duration(status): return bool(status & 0x100)

# Temps restant
def remaining_us(start_us, duration_us, pause_us, now_us, paused):
    if paused:
        return duration_us - (pause_us - start_us)
    return duration_us - (now_us - start_us - pause_us)

# Formatage
def format_time(us):
    secs = max(0, math.ceil(us / 1_000_000))
    if secs >= 3600:
        return f"{secs//3600}:{secs%3600//60:02d}:{secs%60:02d}"
    return f"{secs//60:02d}:{secs%60:02d}"

# Temps au tour lisible
def format_lap_time(us):
    secs = us / 1_000_000
    return f"{int(secs//60)}:{secs%60:06.3f}" if secs >= 60 else f"{secs:.3f}"
```

# Architecture demandée

## Backend (Python + FastAPI)
- Serveur FastAPI sur le PC Windows de la piste
- Poll Firebird toutes les 1 seconde
- API REST :
  - `GET /api/sessions` → liste des sessions du jour (idx, nom, état, temps restant, tours)
  - `GET /api/session/{n}/standings` → classement live (karts, tours, temps, meilleur tour)
  - `GET /api/session/{n}/kart/{k}/laps` → historique tours d'un kart
- WebSocket `/ws/live` → push toutes les secondes : session active + classement
- Détection automatique du fichier DAY du jour
- Gestion propre des reconnexions Firebird

## Frontend (HTML/CSS/JS)
- Servi en statique par FastAPI (`/static/`)
- Page unique responsive (mobile, tablette, TV plein écran)
- Design sombre (thème racing, fond noir/gris foncé)
- Connexion WebSocket pour mise à jour live sans rechargement
- Éléments :
  1. **Header** : logo Karting86, nom de la session active, état
  2. **Timer** : gros countdown central (temps restant), change de couleur (vert → jaune à 60s → rouge à 30s)
  3. **Tableau classement** : position, n° kart, tours, temps total, meilleur tour, dernier tour, écart leader
  4. **Liste sessions** : barre latérale ou menu avec toutes les sessions du jour
  5. **Mode TV** : bouton plein écran, police agrandie

## Contraintes techniques
- Pas de framework JS lourd (pas de React/Vue/Angular). HTML + CSS + JS vanilla ou Alpine.js max
- Pas de build step (pas de npm/webpack). Fichiers statiques directement
- Le code doit tourner sur Windows (Python 3.10+)
- Gérer le cas "aucune session active" avec un écran d'attente élégant
- Polling BDD max 1 req/sec pour ne pas surcharger Firebird

# Livrables

1. `server.py` — Backend FastAPI complet (API + WebSocket + service statique)
2. `static/index.html` — Page HTML du dashboard
3. `static/style.css` — Styles (thème sombre racing)
4. `static/app.js` — Logique frontend (WebSocket, mise à jour DOM)
5. `requirements.txt` — Dépendances Python (fastapi, uvicorn, firebird-driver)
6. Instructions de déploiement

Crée tous les fichiers, complets et fonctionnels. Le code doit être simple, lisible, bien commenté en français.
