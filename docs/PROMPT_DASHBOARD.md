# Mission

Crée un **agent Python** pour Windows qui lit en continu la base de données Firebird d'Apex Timing (logiciel de chronométrage karting GoKarts) et **pousse toutes les données** vers un serveur distant via HTTP POST. Le but : avoir une copie complète et temps réel des données de la piste sur un serveur externe, pour ensuite construire un dashboard live.

# Source de données : Firebird

## Connexion
- Base Firebird 5.0, fichier quotidien : `C:\ApexTiming\Data\DAY<YYYYMMDD>.GO`
- Host: `localhost:3050`, user: `SYSDBA`, password: `masterkey`
- Transactions READ-ONLY uniquement — **ne jamais écrire dans la BDD**
- Librairie Python : `firebird-driver`
- Le fichier change chaque jour → détecter automatiquement le bon fichier selon la date
- Bases annexes dans le même dossier : `CENTER.GO` (paramètres globaux, durées par modèle), `CENTERHIST.GO`, `BOOKINGS.GO`

## Timestamps
Tous les timestamps Firebird sont en **microsecondes depuis 1899-12-30** (format Delphi TDateTime, heure locale du PC).
Conversion vers Python : `unix_ts = (firebird_us - 59_926_435_200_000_000) / 1_000_000`

## Tables connues (non exhaustif — il faut TOUT lire)

### T1_SESSIONS_V8 — Sessions (dans DAY<YYYYMMDD>.GO)
| Colonne | Type | Description |
|---------|------|-------------|
| CIDX | INT | Index session (1-50, pré-créées par GoKarts) |
| CORDER | INT | Ordre d'affichage |
| CSTATUS | INT | Flags : `CIDX << 16` + bits (0x10=démarrée, 0x01=active, 0x20=terminée, 0x100=durée manuelle, 0x04=pause) |
| CSTARTTIME | BIGINT | Début (µs Delphi), 0 = pas encore démarrée |
| CPAUSETIME | BIGINT | En pause: début pause. Après reprise: cumul pauses (µs) |
| CFINISHTIME | BIGINT | Fin (µs), 0 si pas terminée |
| CDURATION | BIGINT | Durée prévue (µs). Ex: 600 000 000 = 10 min |
| CLAPS | INT | Tours total (0 = session chrono/temps) |
| CKART | INT | ID modèle de kart |
| CNAME | VARCHAR | Nom de la session |
| CTIMING | VARCHAR | 'CHRONO' = chrono actif |

### T1_S{n}_RC — Passages karts (n = CIDX de la session)
| Colonne | Type | Description |
|---------|------|-------------|
| CTI | BIGINT | Timestamp passage (µs Delphi) |
| CST | INT | Statut (65282/0xFF02 = départ, 0xFF05 = fin — ignorer pour les tours) |
| CKID | INT | Numéro de kart |
| CDID | INT | ID pilote |
| CTLP | INT | Numéro de tour pour ce kart |
| CTTI | BIGINT | Temps total session ce kart (µs) |
| CLP | BIGINT | Temps au tour (µs) |

### T1_S{n}_DRIVERS_V8 — Pilotes de la session n
Contient les infos pilotes (noms, etc.). **Lire toutes les colonnes** avec `SELECT *`.

### T1_S{n}_R — Autre table par session (résultats ?)
Existe pour chaque session. **Lire toutes les colonnes** avec `SELECT *`.

### TTRACKS_CASES_V20 — Durées auto par modèle (dans CENTER.GO)
| Colonne | Description |
|---------|-------------|
| CTRACK | Piste (1 = principale) |
| CDAY_OF_WEEK | Jour (0 = tous) |
| CKART_MODEL | Modèle de kart (ex: 9=SR5, 11=BIPLACE, 12=LR6 enfants) |
| CFIELD | 11 = champ durée session |
| CVALUE | Durée en µs (ex: 480 000 000 = 8:00 pour LR6) |

## Logique métier

```python
import math

# Déterminer l'état d'une session depuis CSTATUS
def is_active(status): return bool(status & 0x01) and bool(status & 0x10)
def is_paused(status): return bool(status & 0x04)
def is_finished(status): return bool(status & 0x20)
def is_manual_duration(status): return bool(status & 0x100)

# Temps restant en microsecondes
def remaining_us(start_us, duration_us, pause_us, now_us, paused):
    if paused:
        return duration_us - (pause_us - start_us)
    return duration_us - (now_us - start_us - pause_us)

# Formatage temps restant (arrondi vers le HAUT comme GoKarts)
def format_time(us):
    secs = max(0, math.ceil(us / 1_000_000))
    if secs >= 3600:
        return f"{secs//3600}:{secs%3600//60:02d}:{secs%60:02d}"
    return f"{secs//60:02d}:{secs%60:02d}"

# Temps au tour lisible (précision milliseconde)
def format_lap_time(us):
    secs = us / 1_000_000
    return f"{int(secs//60)}:{secs%60:06.3f}" if secs >= 60 else f"{secs:.3f}"
```

# Comportement de l'agent

## Boucle principale (toutes les 1 seconde)

1. **Lister toutes les tables** de la base du jour :
   ```sql
   SELECT RDB$RELATION_NAME FROM RDB$RELATIONS
   WHERE RDB$SYSTEM_FLAG = 0 AND RDB$VIEW_BLR IS NULL
   ```

2. **Premier lancement** : dump complet de chaque table (`SELECT * FROM <table>`) et envoi au serveur

3. **Ensuite (mode incrémental)** :
   - Tables petites (sessions, drivers, config) : renvoi complet à chaque cycle
   - Tables volumineuses (passages `T1_S{n}_RC`) : envoi seulement les **nouvelles lignes** depuis le dernier push (basé sur CTI ou nombre de lignes)

4. **Envoi** : POST HTTP vers le serveur distant avec le JSON complet

5. **Aussi lire CENTER.GO** pour les règles de durée par modèle (table TTRACKS_CASES_V20) — une seule fois au démarrage puis toutes les 10 minutes

## Gestion des erreurs
- Reconnexion automatique si Firebird est indisponible (retry avec backoff 2s → 15s)
- Changement de jour : détecter le nouveau fichier DAY et s'y connecter
- Perte de connexion au serveur distant : buffer les données et renvoyer quand la connexion revient
- Log clair en console de tout ce qui se passe

## Format du POST envoyé au serveur

```json
{
  "api_key": "ma-cle-secrete",
  "timestamp": "2026-10-11T14:30:00",
  "day": "20261011",
  "full_dump": false,
  "tables": {
    "T1_SESSIONS_V8": {
      "columns": ["CIDX", "CSTATUS", "CSTARTTIME", ...],
      "rows": [[1, 65553, 63874...], ...]
    },
    "T1_S3_RC": {
      "columns": ["CTI", "CST", "CKID", "CDID", "CTLP", "CTTI", "CLP"],
      "rows": [[63874..., 65282, 5, 12, 1, 0, 45230000], ...],
      "incremental": true,
      "since_row": 42
    },
    "T1_S3_DRIVERS_V8": {
      "columns": ["...toutes les colonnes trouvées..."],
      "rows": [...]
    }
  },
  "duration_rules": {
    "9": 600000000,
    "11": 600000000,
    "12": 480000000
  }
}
```

# Partie serveur (réception uniquement pour l'instant)

Crée aussi un **mini serveur de réception** (FastAPI) qui :
- Écoute sur `POST /api/push` avec vérification de la clé API
- Stocke les données reçues en mémoire (dict Python)
- Affiche dans la console un résumé de ce qu'il reçoit (sessions actives, nombre de karts, etc.)
- Expose `GET /api/status` pour vérifier que les données arrivent bien
- Expose `GET /api/dump` pour voir le dernier état reçu en JSON brut (debug)

Ce serveur sera enrichi plus tard avec le dashboard complet.

# Livrables

## Agent PC piste
1. `agent/push_agent.py` — Script Python principal
2. `agent/requirements.txt` — Dépendances (firebird-driver, requests)
3. `agent/config.json` — Config exemple (URL serveur, clé API, chemin BDD Firebird)

## Serveur réception
4. `server/receiver.py` — Mini serveur FastAPI de réception
5. `server/requirements.txt` — Dépendances (fastapi, uvicorn)

## Docker
6. `server/Dockerfile` — Pour déployer le serveur sur le dédié
7. `server/docker-compose.yml` — Lancement simple

Crée tous les fichiers, complets et fonctionnels. Le code doit être simple, lisible, bien commenté en français.
