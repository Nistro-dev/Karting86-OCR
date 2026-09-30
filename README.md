# New Kart - Panneau led

Affiche le chrono de session (et les tours) d'**Apex Timing** (logiciel GoKarts) sur un panneau LED Wi-Fi en bord de piste, en lisant **directement la base de données** du logiciel de chrono, sans OCR ni capture d'écran.

Jusqu'à la v2.x l'appli s'appelait « Apex Timing OCR » et lisait l'écran par reconnaissance de caractères. Depuis la v3.0, elle lit la base Firebird de GoKarts / GoServer sur le PC de chrono : temps exact, tours du leader, pause, fin ou annulation vus instantanément, aucun calibrage. L'enquête qui a mené là est dans `docs/apex_findings.md`.

## Fonctionnalités

- **Lecture directe d'Apex Timing** : la base du jour `C:\ApexTiming\Data\DAYAAAAMMJJ.GO` (Firebird, créée par GoKarts à son lancement) est lue **en lecture seule** toutes les 500 ms : session en cours, heure de départ, durée, pauses, fin, nombre de tours de la session et tours du leader. Rien n'est écrit ni modifié côté Apex Timing
- Suivi de course : départ détecté en moins d'une seconde, chrono affiché comme GoKarts (arrondi au supérieur), pause gelée, STOP ou fin de session appliqués aussitôt, réarmement automatique pour la session suivante. Les durées **« Automatique »** de GoKarts sont respectées : les cas particuliers par modèle de kart de la base centrale (`CENTER.GO`, ex. karts enfants LR6 → 8 min) sont lus à la connexion puis toutes les 10 min ; une durée saisie à la main dans la session est prise telle quelle
- Base muette (GoKarts fermé, base du jour pas encore créée, mot de passe changé) : statut **rouge** avec la raison, panneau sur l'**heure**, nouvelles tentatives automatiques toutes les 2 à 15 s
- Conçu pour tourner en production toute la journée sans supervision : réduit dans la zone de notification, tâche planifiée de relance, statut de santé (gris = attente, vert = course suivie, rouge = problème)
- **Panneau LED Wi-Fi** (RHX8 64×16, 8 couleurs) : le minuteur (et les tours, désactivable via `led_show_laps`) pendant la course ; hors course, l'**heure** (`led_idle_clock`). À l'approche de la fin, deux paliers : dans les dernières `led_warn_seconds` secondes (60) ou `led_warn_laps` tours (5), le texte passe en **couleur d'avertissement** (`led_warn_color`, jaune), puis dans les dernières `led_alert_seconds` secondes (30) ou `led_alert_laps` tours (2) en **couleur d'alerte** (`led_alert_color`, rouge). **Tours seuls** (`led_laps_only`) n'affiche que le compteur de tours. **Panneau à l'envers** (`led_rotate_180`) tourne toute l'image de 180° pour un panneau monté tête en bas. Le décompte est envoyé **par tranches de 2 min** (`led_resync_minutes`) sous forme de programmes que le panneau joue tout seul (une trame par seconde ; bref clignotement au changement de tranche). L'appli rejoint elle-même le Wi-Fi du panneau (`RHX8-…`) et s'y reconnecte toute seule ; battement de cœur, écran éteint à la fermeture, luminosité 1 à 16, couleurs (texte, avertissement, alerte) choisies parmi les 7 couleurs affichables du panneau (rouge, vert, jaune, bleu, magenta, cyan, blanc : pas d'orange ni de nuances, le panneau n'a qu'un bit par canal)
- Habillage New Kart Poitiers (logo, palette rouge/noir)
- Écriture du timer courant dans `timer.txt` (lisible par une appli externe) et journal applicatif avec rotation quotidienne

## Installation (Windows)

### Option A - Installeur (recommandé)

1. Récupérer `NewKartPanneauLed_Setup.exe` (release GitHub, ou généré via `build\build.bat`)
2. Double-cliquer dessus : raccourcis Menu Démarrer / Bureau, et case **« Lancer à l'ouverture de session et relancer automatiquement »** : une tâche planifiée (`NewKartPanneauLed`) démarre l'appli réduite dans la zone de notification à chaque ouverture de session et la relance dans la minute si elle s'arrête. Une installation par-dessus « Apex Timing OCR » (v2.x) reprend les réglages du panneau LED et supprime l'ancienne tâche planifiée
3. Rien d'autre à installer : le serveur Firebird et son `fbclient.dll` sont ceux d'Apex Timing, déjà sur le PC de chrono. Pas besoin de Python

### Option B - Sources Python

1. Copier le dossier sur le PC
2. Double-cliquer **install.bat** (installe Python et les dépendances via winget)
3. Double-cliquer **run.bat**

## Utilisation

L'appli a deux fenêtres :
- **Fenêtre principale** : minimaliste (logo, statut, panneau LED, gros timer) — c'est ce qui tourne au quotidien
- **Fenêtre dev** (`Ctrl+Maj+D` depuis la fenêtre principale) : trois onglets — **Apex Timing** (statut de la base, session en cours, dossier des bases, connexion Firebird, cadence, boutons Démarrer / Arrêter / Tester la base), **Panneau LED** (IP, mot de passe, Wi-Fi auto, couleurs, luminosité, tours, heure hors course, orientation, tranches, alerte) et **Diagnostics** (statut détaillé, journal, niveau de log, dossier des journaux, config.json)

Au lancement, l'appli se réduit dans la zone de notification, ouvre la base du jour et se connecte au panneau : **aucune action manuelle en usage normal**. Utiliser **Quitter** dans le menu de l'icône systray pour l'arrêter complètement.

## Fichiers, journal et configuration

Tout est stocké dans **`%LOCALAPPDATA%\NewKartPanneauLed\`** (`C:\Users\<utilisateur>\AppData\Local\NewKartPanneauLed\`), conservé lors des mises à jour.

| Fichier | Contenu |
|---|---|
| `logs\apex_ocr.log` | **Journal** du jour (`apex_ocr.log.AAAA-MM-JJ` pour les jours précédents, conservés 30 jours) |
| `config.json` | Configuration (voir ci-dessous) |
| `timer.txt` | Temps actuel, réécrit à chaque changement (lisible par une appli externe) |

### Réglages (`config.json`, ou fenêtre dev)

| Clé | Défaut | Rôle |
|---|---|---|
| `apex_data_dir` | `C:\ApexTiming\Data` | dossier des bases journalières `DAYAAAAMMJJ.GO` |
| `apex_db_host` / `apex_db_user` / `apex_db_password` | `localhost` / `SYSDBA` / `masterkey` | connexion Firebird (compte par défaut du serveur d'Apex Timing) |
| `apex_fbclient_path` | vide | `fbclient.dll` 64 bits ; vide = celui du serveur Firebird installé (`C:\Program Files\Firebird\Firebird_5_0`) |
| `apex_poll_ms` | 500 | cadence de lecture de la base |
| `apex_stale_seconds` | 10 | base muette depuis ce délai → statut rouge, session en cours abandonnée |
| `led_*` | | panneau LED : `led_host`, `led_password`, `led_brightness`, `led_show_laps`, `led_laps_only`, `led_idle_clock`, `led_rotate_180`, `led_resync_minutes`, `led_wifi_autoconnect`, `led_color`, `led_warn_color`, `led_warn_seconds`, `led_warn_laps`, `led_alert_color`, `led_alert_seconds`, `led_alert_laps`, `led_enabled` (`false` pour se passer du panneau) |
| `log_level` | `INFO` | `DEBUG` / `INFO` / `WARNING` |

### Journal

`Win + R` → `%LOCALAPPDATA%\NewKartPanneauLed\logs` → ouvrir `apex_ocr.log`. Il contient :
- la base : `Base Apex Timing : CONNECTED`, `Base Apex Timing ouverte en lecture seule : …DAY20260930.GO`, `RETRYING (base du jour absente …)`, `RETRYING (login refusé …)`
- les sessions : `Session 1 démarrée à 11:34:43 (durée 10:00, tours 15)`, chaque changement du timer (`Timer 09:57 (3/15)`), pauses, `Session terminée (SOURCE_ENDED)`
- le panneau LED : connexion, reconnexions, programmes envoyés, envois échoués
- les incidents : `WARNING | Passage en état ERROR`, puis `Sortie de l'état ERROR`

## Dépannage

**Statut rouge « Base Apex Timing injoignable »**
- `base du jour absente` : GoKarts n'a pas encore été lancé aujourd'hui (il crée `DAY<date>.GO` à son démarrage) ; l'appli réessaie toute seule. Si les bases sont ailleurs, corriger le **dossier des bases** (onglet Apex Timing) et cliquer **Tester la base**
- `login refusé` : le mot de passe Firebird a changé → onglet Apex Timing, champ mot de passe
- `fbclient.dll 64 bits introuvable` : serveur Firebird déplacé ou absent → `apex_fbclient_path`
- `connexion refusée` / `timed out` : le service Firebird ne tourne pas (redémarrer le PC ou le service `Firebird Server`)

**Le chrono ne suit pas / s'arrête tout seul** : regarder le journal ; une session « abandonnée (base muette) » signifie que la base n'a plus répondu pendant `apex_stale_seconds`.

**Panneau LED muet pendant ~3 minutes après une coupure Wi-Fi** (statut « Reconnexion… (timed out) ») : la carte RHX8 garde l'ancienne connexion ouverte et n'accepte qu'un client à la fois ; elle la libère au bout de 3-4 min. Pour ne pas attendre : éteindre et rallumer le panneau.

**L'appli ne redémarre pas toute seule après un plantage** : vérifier dans le Planificateur de tâches que la tâche `NewKartPanneauLed` existe et est activée ; sinon réinstaller en cochant la case.

## Architecture

```
main.py                    point d'entrée (DPI awareness, --selftest, lancement de App)
apex_ocr/                  (nom de paquet historique)
  app.py                   orchestrateur : relie config, source Apex Timing, session, santé, panneau LED, UI
  config.py                configuration persistée (AppConfig), reprise de la config 2.x
  paths.py                 emplacements sur disque
  logging_setup.py         logger applicatif (rotation quotidienne)
  readings.py              lectures structurées (temps + tours) et conversions
  session.py               machine à états de la session de course (pure logique, testée)
  health.py                statut de santé (pure logique, testé)
  power.py                 veille / reprise / arrêt Windows
  source/
    apex_live.py           lecture de la base Firebird de GoKarts : décodage (pure logique, testée) + thread de lecture avec reconnexion
  ui/
    main_window.py         fenêtre principale minimaliste
    dev_window.py          fenêtre dev (Apex Timing / Panneau LED / Diagnostics), Ctrl+Maj+D
    tray.py                icône systray multi-états
    branding.py            logo, palette New Kart Poitiers, nom de l'appli, libellés d'état
    theme_newkart.json     thème CustomTkinter
  led/
    panel.py               pilotage Wi-Fi du panneau RHX8 (thread dédié)
    content.py             ce que le panneau affiche selon l'état de la session (pure logique, testée)
    rendering.py           rendu 64×16 à 8 couleurs, rotation 180°, programme joué par le panneau
    protocol.py            protocole TCP RHX8
    wifi.py                rattachement au Wi-Fi « RHX8-… » via netsh
    rgb_template.bin       gabarit binaire du programme RHX8
docs/
  apex_findings.md         ce qui a été trouvé dans Apex Timing (base, tables, statuts, mesures)
  BRIEF_APEX_LIVE.md       le brief de départ de cette enquête
tests/                     tests unitaires (source Apex Timing, session, santé, LED, config, Wi-Fi, veille)
```

## Développement

```
py -m pip install -r requirements-dev.txt
py -m pytest
```

## Build de l'exe et de l'installeur

`build\build.bat` : installe Python/Inno Setup si besoin (winget), les dépendances, génère l'icône, compile l'exe (PyInstaller) puis l'installeur (Inno Setup) → `dist_installer\NewKartPanneauLed_Setup.exe` (~35 Mo, plus de Tesseract embarqué).

Sur une machine sans rien : `irm https://raw.githubusercontent.com/Nistro-dev/Karting86-OCR/main/build/build_and_cleanup.ps1 | iex` (clone, build, copie l'installeur sur le Bureau, propose de désinstaller les outils installés).

Le modèle de la tâche planifiée est `build\startup_task.xml`.

## Stack technique

- Python 3.12, CustomTkinter (interface), Pillow (icônes), pywin32 (veille/arrêt Windows), pystray (zone de notification)
- firebird-driver (lecture de la base d'Apex Timing, via le `fbclient.dll` du serveur Firebird 5 installé avec GoKarts)
- pytest (tests), PyInstaller + Inno Setup (packaging)
