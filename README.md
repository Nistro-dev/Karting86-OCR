# Karting86 OCR - Apex Timing Timer Extractor

Outil d'extraction en temps réel du timer/compteur de tours de l'application **Apex Timing** (chronométrage karting) par reconnaissance optique de caractères (OCR), pour l'afficher sur un panneau LED en bord de piste.

Apex Timing ne propose ni API ni port local pour récupérer ces données. Cette application capture la zone d'écran où elles sont affichées, extrait le texte par OCR, et l'envoie au panneau LED (et dans `timer.txt`).

## Fonctionnalités

- Sélection de la fenêtre Apex Timing parmi les fenêtres ouvertes, et capture de son contenu réel (`PrintWindow`) : fonctionne même en arrière-plan ou masquée
- Une seule zone à définir, contenant temps seul (`mm:ss`, `hh:mm:ss`) ou temps + tours (`tt/tt mm:ss`, `ttt/ttt hh:mm:ss`) — le format est **détecté automatiquement**
- Détection de départ fiable : une lecture isolée n'arme rien ; il faut voir le temps **diminuer** pour confirmer un vrai départ
- Une fois la course en cours : le temps affiché suit une horloge interne fluide (pas de saccades), resynchronisée discrètement si l'OCR dérive au-delà d'une tolérance réglable ; le compteur de tours, lui, est mis à jour immédiatement à chaque lecture
- Arrêt automatique de la session uniquement quand le **temps** s'arrête vraiment (atteint zéro, annulé/réinitialisé sur la source, ou (filet de sécurité) l'OCR ne lit plus rien pendant trop longtemps) — atteindre le total de tours (ex: 20/20) n'arrête pas la session, le temps peut continuer sur la source. Puis réarmement automatique pour la prochaine course, sans action manuelle
- Conçu pour tourner en production toute la journée sans supervision : récupère sa configuration au démarrage, retente en arrière-plan si la fenêtre source n'est pas encore ouverte, et remonte un statut de santé dans la zone de notification (gris = attente, vert = course suivie, rouge = problème). Pas de notification Windows (trop intrusif), l'historique reste dans le log
- Calibration automatique du seuil (bouton **Auto**) : teste plusieurs captures dans le temps sur une plage de seuils et retient le plus robuste
- Habillage aux couleurs New Kart Poitiers (logo, palette rouge/noir) sur la fenêtre principale et l'icône
- **Panneau LED Wi-Fi** (RHX8 64×16, 8 couleurs) : le minuteur (et les tours s'il y en a, désactivable via `led_show_laps`) s'affiche sur le panneau pendant la course ; hors course, le panneau montre l'**heure** (HH:MM, renvoyée à chaque changement de minute). Dans les dernières `led_alert_seconds` secondes ou `led_alert_laps` tours, le texte passe en **couleur d'alerte** (`led_alert_color`, pré-calculée dans les trames : pas de renvoi au passage du seuil) ; l'interrupteur **Tours seuls** (`led_laps_only`) n'affiche que le compteur de tours. Le décompte est envoyé **par tranches de 2 min** (`led_resync_minutes`) sous forme de programmes que le panneau joue tout seul (une trame par seconde, sans clignotement à l'intérieur d'une tranche ; bref clignotement au changement de tranche, le panneau repartant du début au bout de ~4 min) ; l'appli ne renvoie sinon quelque chose qu'en cas de resynchronisation, de changement de tours ou de chrono arrêté. L'appli rejoint elle-même le Wi-Fi du panneau (`RHX8-…`, réseau ouvert) et s'y connecte à chaque lancement, avec nouvelles tentatives automatiques (Wi-Fi + panneau) en cas de coupure. Un battement de cœur détecte un lien mort en quelques secondes (sans attendre un changement d'affichage) et l'écran est éteint à la fermeture de l'appli. Bouton **Tester** pour vérifier qu'il répond, luminosité réglable (1 à 16), couleur du texte au choix (ramenée à l'une des 8 couleurs du panneau)
- Écriture du timer courant dans `timer.txt` (lisible par une appli externe) et journal applicatif avec rotation quotidienne (rétention configurable)
- `test_timer.html` : page web autonome simulant un chrono Apex Timing (avec ou sans tours, lancement manuel) pour tester l'OCR sans l'application réelle ; installée avec l'appli (bouton **Page de test** dans la fenêtre dev, raccourci dans le menu Démarrer). La boîte du chrono garde toujours la même taille (le texte est réduit si besoin), la zone OCR calibrée reste donc valable

## Installation (Windows)

### Option A - Installeur (recommandé)

1. Récupérer `ApexTimingOCR_Setup.exe` (généré via `build\build.bat`, voir plus bas)
2. Double-cliquer dessus : **Tesseract OCR est embarqué dans l'installateur** et s'installe tout seul s'il est absent (pas besoin d'internet ni de winget ; une seule invite Windows « autoriser ? » car il va dans `C:\Program Files\Tesseract-OCR`). Raccourcis Menu Démarrer / Bureau, et case à cocher **« Lancer à l'ouverture de session et relancer automatiquement »** : une tâche planifiée Windows (`ApexTimingOCR`) démarre l'appli réduite dans la zone de notification à chaque ouverture de session et **la relance dans la minute si elle s'arrête** (crash, fermeture par erreur). Décocher la case (ou désinstaller) supprime la tâche
3. Aucune install de Python nécessaire côté utilisateur, tout est embarqué dans l'exe

### Option B - Sources Python

1. Copier le dossier sur le PC
2. Double-cliquer **install.bat** (installe Python, Tesseract OCR et les dépendances via winget)
3. Double-cliquer **run.bat** pour lancer l'application

## Utilisation

L'appli a deux fenêtres :
- **Fenêtre principale** : minimaliste (logo, statut, gros timer) — c'est ce qui tourne au quotidien en prod
- **Fenêtre dev** (`Ctrl+Maj+D` depuis la fenêtre principale) : trois onglets — **Capture & OCR** (fenêtre source, zone, seuil + calibration, aperçu brut/prétraité avec la dernière lecture, test OCR), **Panneau LED** (IP, mot de passe, Wi-Fi auto, couleurs, luminosité, tours, heure hors course, tranches, alerte) et **Diagnostics** (statut détaillé, journal, niveau de log, boutons « Ouvrir le dossier des journaux » / « Ouvrir config.json ») — masquée par défaut. Les champs numériques sont bornés et appliqués en quittant le champ (une valeur hors plage est refusée et l'ancienne conservée)

Calibration initiale (dans la fenêtre dev) :
1. Sélectionner la fenêtre Apex Timing dans le menu déroulant
2. Cliquer **Définir la zone** et dessiner un rectangle autour du timer (et du compteur de tours s'il est présent dans la même zone)
3. Cliquer **Test OCR** pour vérifier la détection et le format reconnu
4. Cliquer **Auto** à côté du seuil pour calibrer automatiquement (ou ajuster manuellement si besoin)
5. *(optionnel)* Panneau LED (onglet **Panneau LED**) : allumer le panneau : à chaque lancement l'appli rejoint elle-même son réseau Wi-Fi `RHX8-…` (réseau ouvert, profil Windows créé au besoin) et s'y connecte, puis réessaie toutes les 30 s tant qu'il est injoignable (panneau allumé après l'appli, Wi-Fi coupé…). L'IP `192.168.47.1` ne change jamais (le panneau est lui-même le point d'accès). **Tester** vérifie qu'il répond ; **Déconnecter** ne vaut que pour la session en cours (l'écran est vidé). Le bouton **Couleur** change la couleur du texte (le panneau n'a que 8 couleurs, le bouton montre celle réellement affichée) et le curseur **Luminosité** règle l'intensité (1 à 16). Le mot de passe du panneau (`LED12345678` par défaut), le rattachement Wi-Fi automatique, les tours à côté du temps, l'heure hors course (sinon écran noir) et la longueur des tranches se règlent dans le même onglet. Pour se passer complètement du panneau : `led_enabled: false` dans `config.json` (bouton « Ouvrir config.json » de l'onglet Diagnostics)

Une fois fenêtre + zone configurées, l'OCR démarre automatiquement à chaque lancement, la fenêtre principale se réduit direct dans la zone de notification — aucune action manuelle requise en usage normal. Utiliser **Quitter** dans le menu de l'icône systray pour arrêter complètement l'application.

## Fichiers, journal et configuration

Tout est stocké dans **`%LOCALAPPDATA%\ApexTimingOCR\`**, c'est-à-dire `C:\Users\<utilisateur>\AppData\Local\ApexTimingOCR\`. Ce dossier n'est pas celui d'installation, et il est conservé lors des mises à jour.

| Fichier | Contenu |
|---|---|
| `logs\apex_ocr.log` | **Journal** du jour |
| `logs\apex_ocr.log.AAAA-MM-JJ` | Journaux des jours précédents (un fichier par jour, conservés 30 jours) |
| `config.json` | Configuration : fenêtre source, zone (+ taille de fenêtre de référence), seuil, panneau LED (`led_host`, `led_password`, `led_brightness`, `led_show_laps`, `led_laps_only`, `led_idle_clock`, `led_resync_minutes`, `led_wifi_autoconnect`, couleurs `led_color`/`led_alert_color`, seuils `led_alert_seconds`/`led_alert_laps`), niveau de log |
| `timer.txt` | Temps actuel, réécrit à chaque changement (lisible par une appli externe) |

### Ouvrir le journal

1. `Win + R`
2. Coller `%LOCALAPPDATA%\ApexTimingOCR\logs` puis Entrée
3. Ouvrir `apex_ocr.log` avec le Bloc-notes

Le journal est horodaté (`date | niveau | message`) et contient :
- chaque changement du timer pendant une course (`INFO | Timer 09:35 (3/20)`)
- les fins de session et leur cause (temps écoulé, course annulée, signal perdu)
- les incidents : `WARNING | Passage en état ERROR` (capture/OCR en échec), puis `Sortie de l'état ERROR` au retour à la normale
- le panneau LED : connexion (`Panneau LED : CONNECTED`), reconnexions (`RETRYING` + raison), programmes envoyés (`décompte envoyé depuis 09:57 (131 trames, suite dans 120 s, 0.7 s de transfert)`, `affiche 05:00 (fixe)`) et envois échoués

Pour chercher uniquement les problèmes, filtrer les lignes qui contiennent `WARNING`.

Le cadre « Journal » de la fenêtre dev (`Ctrl+Maj+D`) n'affiche que les messages de la session en cours et n'est pas sauvegardé : pour l'historique, utiliser le fichier `apex_ocr.log`.

Pour repartir de zéro (nouvelle calibration, oublier le panneau LED), quitter l'appli et supprimer `config.json`.

## Limites connues

**Confusion de chiffres par l'OCR (0 lu comme 6, 2, ou 8)** — observée en test sur `test_timer_mini.html` (police Consolas). Un seuil bien calibré élimine les lectures les plus aberrantes (la validation rejette par exemple les minutes/secondes ≥ 60), mais pas toutes : Tesseract peut lire un `0` comme un `6` tout en restant dans une plage crédible (`10:00` → `10:06`), ce qui passe la validation sans être détecté comme faux.

Deux pistes déjà en place pour limiter ça (`apex_ocr/ocr/engine.py`, `preprocess.py`) :
- upscale plus agressif avant OCR (plus de détail pour le classifieur)
- mode numérique Tesseract (`classify_bln_numeric_mode=1`)

**Mais l'hypothèse la plus probable reste la police/le rendu de la source réelle** (pas encore connue à ce stade — testé uniquement contre une page de simulation). **À vérifier une fois l'appli calibrée sur le vrai écran Apex Timing du client** : si la confusion persiste avec la police réelle, il faudra soit essayer d'autres polices de rendu si c'est en notre contrôle, soit ajouter une correction heuristique ciblée (ex: vérifier la plausibilité d'une valeur par rapport à l'historique récent), soit l'accepter comme limite et informer l'utilisateur que la précision OCR dépend du rendu source.

## Architecture

```
main.py                    point d'entrée (DPI awareness, --selftest, lancement de App)
apex_ocr/
  app.py                   orchestrateur : relie config, capture, OCR, session, santé, UI
  config.py                configuration persistée (AppConfig)
  paths.py                 emplacements sur disque
  logging_setup.py         logger applicatif (rotation quotidienne)
  capture.py                capture de fenêtre Windows (PrintWindow + repli mss)
  session.py                machine à états de la session de course (pure logique, testée)
  health.py                  statut de santé du pipeline (pure logique, testé)
  ocr/
    parsing.py               parsing du texte OCR brut -> lectures structurées (pure logique, testé)
    preprocess.py             prétraitement image (seuillage, upscale)
    engine.py                 appel Tesseract
    calibration.py            calibration auto du seuil (multi-échantillons, pure logique testée)
  ui/
    main_window.py            fenêtre principale minimaliste (logo, statut, timer)
    dev_window.py              fenêtre dev en onglets (Capture & OCR / Panneau LED / Diagnostics), masquée par défaut, Ctrl+Maj+D pour l'ouvrir
    zone_selector.py          sélection de la zone à la souris
  led/
    panel.py                  pilotage Wi-Fi du panneau RHX8 (thread dédié : connexion, reconnexion auto, envoi du programme de décompte)
    content.py                ce que le panneau affiche selon l'état de la session (pure logique, testée)
    rendering.py              rendu 64×16 à 8 couleurs (chiffres 7 segments, tours) et construction du programme joué par le panneau
    protocol.py               protocole TCP RHX8 (login RC5, luminosité, transfert de programme), fonctions pures testées
    wifi.py                   rattachement optionnel au Wi-Fi « RHX8-… » via netsh (Windows, jamais bloquant pour l'UI)
    rgb_template.bin          gabarit binaire du programme RHX8 (embarqué dans l'exe)
    tray.py                   icône systray multi-états
    branding.py               logo, palette New Kart Poitiers et libellés d'état partagés (santé, panneau LED)
    theme_newkart.json        thème CustomTkinter (rouge/noir, dérivé du logo)
assets/
  logo_favicon.png             marque seule, fond transparent (bandeau fenêtre)
  logo_square.png               carré arrondi (icône exe / fenêtre / barre des tâches)
  logo_round.png                 badge rond (icône systray)
tests/                       tests unitaires (parsing, machine à états, santé, calibration)
```

Le cœur logique (`session.py`, `health.py`, `ocr/parsing.py`) est indépendant de Tkinter/Windows et entièrement couvert par des tests unitaires (horloge injectée via un paramètre `now`, pas d'appel direct à `time.monotonic()`). La couche UI et la capture Windows ne sont testées que manuellement (nécessitent un vrai écran/Apex Timing).

## Développement

```
py -m pip install -r requirements-dev.txt
py -m pytest
```

## Build de l'exe et de l'installeur

### Sur une machine de dev (outils déjà installés)

`build\build.bat` automatise tout (installe Python/Inno Setup si besoin via winget, installe les dépendances, génère l'icône, compile l'exe avec PyInstaller, télécharge l'installeur Tesseract OCR dans `build\vendor\` via `build\fetch_tesseract.ps1` — ~50 Mo, une seule fois, git-ignoré — puis compile l'installeur avec Inno Setup, qui l'embarque). Résultat : `dist_installer\ApexTimingOCR_Setup.exe` (~130 Mo). Sans accès à GitHub, déposer l'installeur Tesseract à la main dans `build\vendor\tesseract-setup.exe`.

Le modèle de la tâche planifiée de démarrage est `build\startup_task.xml` (installé à côté de l'exe ; l'installateur y remplace l'utilisateur et le chemin de l'exe, puis l'enregistre avec `schtasks`).

### Sur une machine sans rien (ex : PC client)

Ouvrir PowerShell et coller :

```powershell
irm https://raw.githubusercontent.com/Nistro-dev/Karting86-OCR/main/build/build_and_cleanup.ps1 | iex
```

Le script installe Git, Python et Inno Setup si nécessaire, clone le repo, build l'installateur, le copie sur le Bureau, puis **propose** de désinstaller les outils qu'il a lui-même installés (réponse par défaut : les garder). Au minimum, `ApexTimingOCR_Setup.exe` est sur le Bureau.

## Dépannage

**Le chrono n'est pas lu (statut « Problème », panneau qui reste sur l'heure)**
- La fenêtre source (Brave/Chrome avec Apex Timing ou la page de test) doit être **sur l'écran principal**, ni réduite, ni sur un second écran : Windows ne fournit pas le contenu d'une fenêtre placée hors de l'écran principal (coordonnées négatives) et la capture est vide. Ramener la fenêtre sur l'écran principal suffit, l'appli reprend toute seule.
- Le titre de la fenêtre doit être exactement celui choisi dans la fenêtre dev (bouton ↻ pour rafraîchir la liste) ; un onglet différent au premier plan change le titre.
- Vérifier la zone (bouton **Définir la zone**) après tout changement de taille de fenêtre ou de format d'affichage.

**Tesseract OCR absent** (`tesseract.exe introuvable` dans le journal) : il est normalement installé par l'installateur dans `C:\Program Files\Tesseract-OCR`. Sinon, l'installer à la main (installeur Windows 64 bits : https://github.com/UB-Mannheim/tesseract/releases) en gardant le dossier par défaut, puis relancer l'appli.

**Panneau LED muet pendant ~3 minutes après une coupure Wi-Fi** (statut « Reconnexion… (timed out) » alors que le Wi-Fi est revenu) : la carte RHX8 garde l'ancienne connexion ouverte et n'accepte qu'un seul client à la fois ; elle la libère d'elle-même au bout de 3-4 min et l'appli se reconnecte aussitôt. Pour ne pas attendre : **éteindre et rallumer le panneau** (le redémarrage libère la place immédiatement). Une fermeture normale de l'appli (menu de la zone de notification → Quitter) ne provoque jamais ce blocage.

**Configuration perdue (fenêtre / zone à refaire)** : `config.json` (dossier `%LOCALAPPDATA%\ApexTimingOCR`) est illisible, par exemple après une coupure de courant pendant une sauvegarde ; l'appli repart des valeurs par défaut et le signale dans le journal. Refaire le choix de la fenêtre et la zone dans la fenêtre dev.

**L'appli ne redémarre pas toute seule après un plantage** : vérifier dans le Planificateur de tâches Windows que la tâche `ApexTimingOCR` existe et est activée (elle est créée par l'installateur quand la case de démarrage est cochée) ; sinon réinstaller en cochant la case.

## Stack technique

- Python 3.12
- CustomTkinter (interface)
- Tesseract OCR (via pytesseract)
- Pillow + OpenCV (capture et prétraitement image)
- mss (capture d'écran, repli si PrintWindow indisponible)
- pywin32 (capture de fenêtre via PrintWindow, énumération des écrans)
- pygetwindow (détection des fenêtres)
- pystray (icône dans la zone de notification)
- pytest (tests unitaires)
- PyInstaller + Inno Setup (packaging en .exe / installeur)
