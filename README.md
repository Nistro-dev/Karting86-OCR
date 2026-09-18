# Karting86 OCR - Apex Timing Timer Extractor

Outil d'extraction en temps réel du timer/compteur de tours de l'application **Apex Timing** (chronométrage karting) par reconnaissance optique de caractères (OCR), pour l'afficher en grand sur un écran externe (piste).

Apex Timing ne propose ni API ni port local pour récupérer ces données. Cette application capture la zone d'écran où elles sont affichées, extrait le texte par OCR, et le rend disponible pour un affichage externe.

## Fonctionnalités

- Sélection de la fenêtre Apex Timing parmi les fenêtres ouvertes, et capture de son contenu réel (`PrintWindow`) : fonctionne même en arrière-plan ou masquée
- Une seule zone à définir, contenant temps seul (`mm:ss`, `hh:mm:ss`) ou temps + tours (`tt/tt mm:ss`, `ttt/ttt hh:mm:ss`) — le format est **détecté automatiquement**
- Détection de départ fiable : une lecture isolée n'arme rien ; il faut voir le temps **diminuer** pour confirmer un vrai départ
- Une fois la course en cours : le temps affiché suit une horloge interne fluide (pas de saccades), resynchronisée discrètement si l'OCR dérive au-delà d'une tolérance réglable ; le compteur de tours, lui, est mis à jour immédiatement à chaque lecture
- Arrêt automatique de la session uniquement quand le **temps** s'arrête vraiment (atteint zéro, annulé/réinitialisé sur la source, ou (filet de sécurité) l'OCR ne lit plus rien pendant trop longtemps) — atteindre le total de tours (ex: 20/20) n'arrête pas la session, le temps peut continuer sur la source. Puis réarmement automatique pour la prochaine course, sans action manuelle
- Affichage externe : bouton qui liste les écrans connectés, clic → ouverture direct en plein écran avec le temps et les tours en grand
- Conçu pour tourner en production toute la journée sans supervision : récupère sa configuration au démarrage, retente en arrière-plan si la fenêtre source n'est pas encore ouverte, et remonte un statut de santé dans la zone de notification (gris = attente, vert = course suivie, rouge = problème). Pas de notification Windows (trop intrusif), l'historique reste dans le log
- Calibration automatique du seuil (bouton **Auto**) : teste plusieurs captures dans le temps sur une plage de seuils et retient le plus robuste
- Habillage aux couleurs New Kart Poitiers (logo, palette rouge/noir) sur la fenêtre principale, l'icône et l'affichage externe
- Écriture du timer courant dans `timer.txt` (lisible par une appli externe) et journal applicatif avec rotation quotidienne (rétention configurable)
- `test_timer.html` : page web autonome simulant un chrono Apex Timing (avec ou sans tours) pour tester l'OCR sans l'application réelle

## Installation (Windows)

### Option A - Installeur (recommandé)

1. Récupérer `ApexTimingOCR_Setup.exe` (généré via `build\build.bat`, voir plus bas)
2. Double-cliquer dessus : installation silencieuse de Tesseract OCR si absent, raccourcis Menu Démarrer / Bureau, et case à cocher **« Lancer au démarrage de Windows »** (l'appli démarre alors réduite dans la zone de notification)
3. Aucune install de Python nécessaire côté utilisateur, tout est embarqué dans l'exe

### Option B - Sources Python

1. Copier le dossier sur le PC
2. Double-cliquer **install.bat** (installe Python, Tesseract OCR et les dépendances via winget)
3. Double-cliquer **run.bat** pour lancer l'application

## Utilisation

L'appli a deux fenêtres :
- **Fenêtre principale** : minimaliste (logo, statut, gros timer) — c'est ce qui tourne au quotidien en prod
- **Fenêtre dev** (`Ctrl+Maj+D` depuis la fenêtre principale) : configuration, calibration, test OCR, journal, affichage externe — masquée par défaut

Calibration initiale (dans la fenêtre dev) :
1. Sélectionner la fenêtre Apex Timing dans le menu déroulant
2. Cliquer **Définir la zone** et dessiner un rectangle autour du timer (et du compteur de tours s'il est présent dans la même zone)
3. Cliquer **Test OCR** pour vérifier la détection et le format reconnu
4. Cliquer **Auto** à côté du seuil pour calibrer automatiquement (ou ajuster manuellement si besoin)
5. Cliquer **Affichage externe**, survoler la liste pour repérer l'écran (cadre rouge), choisir : ouverture directe en plein écran. L'écran choisi est mémorisé et se rouvre automatiquement aux lancements suivants. Pour fermer : re-cliquer **Affichage externe** dans la fenêtre dev (le plus fiable), ou le petit ✕ discret en haut à droite de l'écran externe

Une fois fenêtre + zone configurées, l'OCR démarre automatiquement à chaque lancement, la fenêtre principale se réduit direct dans la zone de notification, et l'affichage externe se rouvre sur l'écran mémorisé — aucune action manuelle requise en usage normal. Utiliser **Quitter** dans le menu de l'icône systray pour arrêter complètement l'application.

## Sortie

| Emplacement | Contenu |
|---|---|
| `timer.txt` | Temps actuel (écrasé à chaque changement) |
| `logs/apex_ocr.log` | Journal horodaté (changements de timer + incidents), rotation quotidienne |

Ces fichiers (ainsi que `config.json`) sont stockés dans `%LOCALAPPDATA%\ApexTimingOCR\`.

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
    dev_window.py              fenêtre dev (config/calibration/journal/test OCR/affichage externe), masquée par défaut, Ctrl+Maj+D pour l'ouvrir
    zone_selector.py          sélection de la zone à la souris
    screen_picker.py          liste des écrans connectés (+ repère visuel au survol)
    external_display.py       affichage plein écran (piste)
    tray.py                   icône systray multi-états
    branding.py               logo + palette New Kart Poitiers
    theme_newkart.json        thème CustomTkinter (rouge/noir, dérivé du logo)
assets/
  logo_newkart_poitiers.png   logo source (utilisé pour l'icône, la fenêtre, l'affichage externe)
tests/                       tests unitaires (parsing, machine à états, santé, calibration)
```

Le cœur logique (`session.py`, `health.py`, `ocr/parsing.py`) est indépendant de Tkinter/Windows et entièrement couvert par des tests unitaires (horloge injectée via un paramètre `now`, pas d'appel direct à `time.monotonic()`). La couche UI et la capture Windows ne sont testées que manuellement (nécessitent un vrai écran/Apex Timing).

## Développement

```
py -m pip install -r requirements-dev.txt
py -m pytest
```

## Build de l'exe et de l'installeur

`build\build.bat` automatise tout (installe Python/Inno Setup si besoin via winget, installe les dépendances, génère l'icône, compile l'exe avec PyInstaller puis l'installeur avec Inno Setup). Résultat : `dist_installer\ApexTimingOCR_Setup.exe`.

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
