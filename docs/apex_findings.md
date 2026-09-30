# Apex Timing (GoKarts) — où sont les données de session, sans OCR

Enquête du 30/09/2026 sur le PC de chrono du karting (brief : `docs/BRIEF_APEX_LIVE.md`).
Tout a été fait **en lecture seule** : aucun fichier d'Apex Timing modifié ou supprimé,
aucune session lancée par l'appli (les sessions test ont été lancées par Maël dans GoKarts).

## 1. Installation trouvée

| Élément | Valeur |
|---|---|
| Logiciel de chrono | **GoKarts 4.70.06** (`C:\ApexTiming\GoKarts\GoKarts.exe`, appli Delphi 32 bits) |
| Serveur de données | **GoServer 4.70.06** (`C:\ApexTiming\GoServer\GoServer.exe`), écoute `127.0.0.1:3074` (protocole interne GoKarts/GoTV) |
| Base de données | **Firebird 5.0** (service `firebird`, port 3050, `C:\Program Files\Firebird\Firebird_5_0`), fichiers `C:\ApexTiming\Data\*.GO` (une base **par jour** : `DAYAAAAMMJJ.GO`, plus `CENTER.GO`, `CENTERHIST.GO`, `BOOKINGS.GO`…) |
| Affichage TV | GoTV 4.70.06 (2e écran), client de GoServer/Firebird comme GoKarts |
| Décodeur | **Chronelec Protime Elite sur COM3** (journal `chronelecprotimeelite_com3.log`, interrogé toutes les 15 s hors session) |
| Autre poste | Un 2e GoKarts à l'accueil (`PF-8CC5501SVS`, 192.168.1.54) se connecte à ce PC |
| Ports ouverts par GoKarts | TCP **9101** (muet à une requête HTTP ou brute) et **9127** (répond `<connection key="…"/>` + ETX : protocole XML propriétaire avec défi, utilisé par le poste de l'accueil) |
| Live timing web | GoServer synchronise vers apex-timing.com (`WebServerSync`) ; le PC n'a pas toujours internet (`unable to connect apex timing server` dans `GoServer\system.log`) |

## 2. Pistes du brief, dans l'ordre

1. **Serveur live local** : les ports 9101/9127 ne sont pas du HTTP/WebSocket. 9127 parle un XML propriétaire avec clé de session ; sans documentation ni capture d'un client, décodage trop risqué. **Écarté.**
2. **Flux réseau** : GoKarts ↔ GoServer passe par `127.0.0.1:3074` (protocole binaire propriétaire) ; le décodeur est en série (COM3), pas sur le réseau. **Écarté** (capture loopback possible mais inutile vu la piste 4).
3. **UI Automation** : la fenêtre GoKarts n'expose que des `Pane` Delphi (`TAxPanel`, `TAxGrid`, `TDialogTiming`…) sans aucun texte : le chrono est dessiné, pas un contrôle. Idem pour GoTV. **Écarté.**
4. **Fichiers / base de données** : **retenue.** La base Firebird du jour contient la session en cours avec son heure de départ exacte, sa durée, ses pauses, sa fin, et les passages (tours) de chaque kart. Lecture possible en Python (`firebird-driver` + `fbclient.dll` 64 bits du serveur), transaction **read-only**, compte Firebird par défaut (`SYSDBA`).

## 3. La base du jour : ce qui compte

Base : `localhost:C:\ApexTiming\Data\DAY<AAAAMMJJ>.GO` (créée par GoKarts à son lancement ; les
50 sessions de la journée y sont pré-créées).

**Table `T1_SESSIONS_V8`** (une ligne par session, `T1` = piste 1) :

| Colonne | Sens (vérifié) |
|---|---|
| `CIDX` | numéro de session (1..50) ; les tables `T1_S<CIDX>_RC` / `_R` / `_DRIVERS_V8` s'y rattachent |
| `CORDER` | ordre d'affichage |
| `CSTATUS` | `CIDX << 16` + bits : `0x10` = démarrée, `0x01` = en cours (vu `0x10011` pendant la session), `0x20` = terminée (+ `0x100`, `0x400` : états de clôture/impression) |
| `CSTARTTIME`, `CPAUSETIME`, `CFINISHTIME` | **microsecondes depuis le 30/12/1899 (TDateTime Delphi), heure locale du PC**, 0 = pas encore |
| `CDURATION` | durée de la session en **microsecondes** (600 000 000 = 10:00) |
| `CLAPS` | nombre de tours de la session (0 = session au temps) |
| `CUPDATE` | compteur de modifications |
| `CNAME`, `CTIMING` | nom libre, `'CHRONO'` = chrono actif |

**Tables `T1_S<n>_RC`** (passages de la session n) : `CTI` horodatage (même unité), `CKID` kart,
`CDID` pilote, `CTLP` **numéro de tour** du kart, `CTTI` temps total, `CLP` temps au tour (µs).
La 1re ligne (`CST = 65282`) est l'événement de départ (`CTI = CSTARTTIME`).

**Temps restant** = `CDURATION − (maintenant − CSTARTTIME)` (pause à gérer via `CPAUSETIME`).
**Tours** = `max(CTLP)` de `T1_S<n>_RC` (leader) sur `CLAPS`, seulement si `CLAPS > 0`.

### Mesures (session test 1 du 30/09, 10 min, sans kart)

- Départ dans GoKarts → ligne `T1_SESSIONS_V8` mise à jour (`CSTARTTIME`, statut `0x10011`) en **< 100 ms** (départ 11:17:02.350, lu 11:17:02.436).
- Restant calculé 09:59 à +0,1 s puis décrémente à la seconde, aligné sur le chrono de GoKarts.
- Coût : une transaction read-only par lecture (2 requêtes), négligeable pour Firebird.

### Pause, reprise, arrêt (session test 1 du 30/09, vérifié)

| Action dans GoKarts | Ce que la base montre |
|---|---|
| Pause (11:20:16) | `CSTATUS` bas = `0x05` (bit `0x04` pause), `CPAUSETIME` = **horodatage du début de pause** ; le chrono de GoKarts se fige |
| Reprise (11:20:23) | `CSTATUS` bas = `0x11`, `CPAUSETIME` = **cumul des pauses** en µs (6 368 000 = 6,4 s) → restant = `CDURATION − (maintenant − CSTARTTIME − CPAUSETIME)` |
| STOP manuel (11:20:29) | la ligne est **remise à zéro** (`CSTARTTIME = 0`) ; GoKarts la réécrit ~1,5 s plus tard puis la remet à zéro : la source ignore une réapparition de la session qui vient de finir (même ligne, même heure de départ) |
| Fin normale (27/09) | `CFINISHTIME` posé, bit `0x20` ; `CSTARTTIME` conservé |

Une ligne « démarrée » (`0x10`) sans bit actif (`0x01`) ni fin est un résidu (session 1 du 27/09 :
lancée à 08:45, jamais clôturée) : seules les lignes avec le bit `0x01` comptent.

### Validation en conditions réelles (30/09, 11:31 → 11:45)

Appli v2.8.0 en `source: "apex_live"`, panneau LED branché, sessions test lancées par Maël dans GoKarts
avec et sans tours (`CLAPS = 15`), pause/reprise et arrêt : « parfait, identique à GoKarts ». Aucun
appel Tesseract pendant tout le test (journal : `Source directe Apex Timing active : l'OCR est en pause`).

### Sessions « enfants »

Le 27/09, des sessions à `CDURATION = 600 000 000` (10:00) se sont terminées après 8:01 : ce sont
des sessions enfants, dont le chrono **part de 08:00 à l'écran** (dixit Maël). La durée réelle n'est
donc pas toujours `CDURATION` : à vérifier sur une session enfants (colonne `CTYPE`/`CGAME_MODE`,
ou autre table de paramètres) avant de faire confiance à `CDURATION` pour ce type.

## 4. Ce qui reste à faire / limites

- Sessions enfants : trouver d'où vient le 08:00 (à observer sur une vraie session enfants : `CDURATION`
  reste-t-il à 600 s pendant qu'elle tourne ?).
- Décision de Maël après validation : l'OCR a été **retiré complètement** en v3.0.0 (appli renommée
  « New Kart - Panneau led ») ; la base est la seule source. Sans base : statut rouge, panneau sur l'heure,
  nouvelles tentatives automatiques.
- Changement de jour : ouvrir `DAY<jour>.GO` du jour, retenter si la base n'existe pas encore (GoKarts pas lancé), repli OCR.
- Le compte `SYSDBA` par défaut fonctionne ; si le mot de passe Firebird change, la source tombe et l'OCR reprend.
