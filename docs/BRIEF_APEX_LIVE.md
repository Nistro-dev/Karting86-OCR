# Brief pour Claude — lire Apex Timing en direct (sans OCR)

> **Comment s'en servir :** ouvrir Claude Code dans ce dépôt, sur le PC du karting, avec le
> logiciel **Apex Timing** (application Windows) ouvert et une session de chrono en cours ou
> possible, puis taper :
> `Lis docs/BRIEF_APEX_LIVE.md et exécute-le de bout en bout. Pose-moi des questions si besoin.`

## 1. Contexte (à lire d'abord)

- **Apex Timing est un logiciel Windows** installé sur le PC du karting (chronométrage des
  sessions : chrono de session, tours, pilotes). Ce n'est **pas** un site web.
- Cette appli (`apex_ocr/`) lit le **chrono de session** et le **compteur de tours** en capturant
  la **fenêtre** d'Apex Timing (`apex_ocr/capture.py`, `PrintWindow`) et en faisant de l'**OCR**
  (Tesseract) sur une zone calibrée. Elle affiche le temps sur un panneau LED Wi‑Fi
  (`apex_ocr/led/`) et gère le cycle de la course (`apex_ocr/session.py`).
- `test_timer.html` est **uniquement une page de test** qui imite l'affichage d'Apex Timing pour
  développer sans le logiciel. Elle ne dit rien de la vraie source de données. Ne la prends pas
  comme référence pour ce travail.
- L'OCR est la source de tous les problèmes restants : chiffres confondus (0↔6/9, 1↔7), `:` lu
  comme `/`, fenêtre déplacée, charge CPU. **Objectif : remplacer l'OCR par une lecture directe
  et exacte des données d'Apex Timing**, en gardant l'OCR comme repli.
- Demande à Maël : la version d'Apex Timing, où il est installé, s'il tourne sur le même PC que
  cette appli ou sur un autre PC du réseau, et comment il reçoit le chronométrage (décodeur de
  transpondeurs branché en USB/réseau ? serveur distant ?).

## 2. Ce que tu cherches

Trouver **d'où l'application Apex Timing tire ou publie** le chrono de session et les tours, et
le moyen le plus fiable de le lire sans OCR. Pistes par ordre de préférence — **le premier qui
marche suffit** :

1. **Un serveur « live timing » local.** Apex Timing publie normalement un live timing web
   (le site `apex-timing.com/live-timing/...`). Le logiciel Windows peut exposer ou alimenter
   un serveur HTTP/WebSocket **local** (souvent un port sur `localhost` ou sur le PC de chrono).
   Si oui : on s'y connecte en Python → lecture exacte, sans capture d'écran.
2. **Le flux réseau du chronométrage.** Le logiciel reçoit les passages (transpondeurs) et/ou
   envoie le live à un serveur. Le chrono de session et les tours passent peut‑être en clair
   (TCP/UDP, JSON ou texte séparé par `|`). Si oui : on écoute/décode ce flux.
3. **Les contrôles de la fenêtre lisibles par UI Automation.** Si le chrono est un contrôle
   Windows natif (texte lisible via l'API UI Automation : `pywinauto` backend `uia` ou le
   module `uiautomation`), on lit sa valeur directement — sans OCR, même fenêtre au second plan.
   Si c'est du dessin GDI/OpenGL (texte non exposé), cette piste tombe.
4. **Des fichiers que le logiciel écrit en continu** (export live, base de données SQLite/Access,
   fichiers texte/XML de session, journal). Lire un fichier mis à jour chaque seconde est fiable
   et simple.
5. À défaut : améliorer l'OCR (déjà en place) — ce brief n'est alors pas concluant, dis‑le.

## 3. Où et comment chercher (procédure)

1. **Identifier le processus** : Gestionnaire des tâches → nom de l'exe d'Apex Timing, dossier
   d'installation (`Ouvrir l'emplacement du fichier`), dossier de données
   (`%APPDATA%`, `%LOCALAPPDATA%`, `%PROGRAMDATA%`, dossier d'installation). Note tout dans
   `docs/apex_findings.md`.
2. **Ports et connexions** : pendant une session, `netstat -abno` (admin) et
   `Get-NetTCPConnection -OwningProcess <pid>` / `Get-NetUDPEndpoint` : quels ports le
   processus écoute‑t‑il (serveur local ?) et vers quoi se connecte‑t‑il ? Teste tout port en
   écoute avec un navigateur (`http://localhost:<port>`) et avec `websocat`/Python `websockets`.
3. **Capture réseau** : Wireshark est installé sur le PC de Maël (sinon `winget install
   WiresharkFoundation.Wireshark`). Filtre sur le PID/les ports trouvés ; cherche le chrono en
   clair (`Follow TCP/UDP stream`). Enregistre 1–2 min de capture pendant que le chrono avance
   dans `docs/apex_samples/` (fichiers `.pcapng` + extraits texte).
4. **UI Automation** : `pip install pywinauto` puis
   `Application(backend="uia").connect(title_re=".*Apex.*")` → `dump_tree()` ; cherche un
   contrôle dont le `window_text()` / `Value` change chaque seconde. Si trouvé, note son
   `automation_id` / chemin. Alternative : `inspect.exe` (Windows SDK) ou l'outil *Accessibility
   Insights*.
5. **Fichiers** : `Process Monitor` (Sysinternals, `winget install Microsoft.Sysinternals.ProcessMonitor`)
   filtré sur le processus, opération `WriteFile` : quels fichiers sont écrits pendant la
   session ? Ouvre‑les (texte, XML, SQLite via `sqlite3`, Access via `pyodbc`) et vérifie si le
   chrono/les tours y sont à jour à la seconde.
6. Pour chaque piste testée, note dans `docs/apex_findings.md` : ce qui a été trouvé, un
   échantillon, la fréquence de mise à jour, la fiabilité, et pourquoi tu l'as retenue ou écartée.

## 4. Ce que tu livres

- **`apex_ocr/source/apex_live.py`** : une classe `ApexLiveSource` avec la même sortie que l'OCR
  (un `StrictReading`/`LenientReading` de `apex_ocr/ocr/parsing.py` : `time_text`,
  `laps_done`, `laps_total`), alimentée par la piste retenue (serveur local / flux réseau /
  UI Automation / fichier). Thread dédié, reconnexion ou relecture automatique, jamais bloquant
  pour Tk, journalisation sobre.
- **Branchement dans `apex_ocr/app.py`** : un réglage `source: "ocr" | "apex_live"` dans
  `config.json` + dans la fenêtre dev (onglet Capture) ; quand `apex_live` est actif et reçoit des
  données, le tracker de session (`SessionTracker.on_strict_reading` / `on_lenient_reading`) est
  nourri par lui au lieu de l'OCR ; **si la source tombe > 10 s, repli automatique sur l'OCR** et
  message dans le journal ; retour à la source directe quand elle revient.
- **Tests** : `tests/test_apex_live.py` avec les échantillons enregistrés (décodage → lectures),
  sans réseau ni Apex Timing.
- **Doc** : section « Source Apex Timing en direct » dans `README.md` (ce qui a été trouvé,
  réglages, dépannage) + `docs/apex_findings.md` complet.
- Ne casse pas l'existant : `py -m pytest tests -q` doit rester vert, l'OCR reste utilisable.

## 5. Contraintes et pièges connus

- Le PC du karting n'a pas forcément d'internet ; tout doit marcher en local.
- Ne modifie rien dans Apex Timing lui‑même (pas de plugin, pas de fichier de config du
  logiciel) sans l'accord explicite de Maël : c'est l'outil de chronométrage officiel du circuit.
- Formats attendus en sortie : `MM:SS` et `H:MM:SS` pour le temps, `NN/NN` pour les tours, pour
  ne rien changer dans `session.py` ni le panneau LED.
- **Les tours n'existent jamais sans temps** (règle métier) — pas de lecture « tours seuls ».
- Ne commite rien sans montrer un `git diff --stat` à Maël ; pas de push.

## 6. Critères de réussite

- Pendant une session réelle, le chrono affiché par l'appli (fenêtre principale et panneau LED)
  suit Apex Timing à la seconde près pendant 10 min sans resynchronisation dans le journal.
- Couper la source (fermer Apex Timing ou débrancher) → repli OCR en < 10 s, message clair ;
  la rétablir → retour à la source directe.
- CPU de l'appli nettement plus bas qu'en OCR (aucun appel Tesseract quand la source est active).
