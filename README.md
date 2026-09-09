# Karting86 OCR - Apex Timing Timer Extractor

Outil d'extraction en temps reel du compteur de temps restant de l'application **Apex Timing** (chronometrage karting) par reconnaissance optique de caracteres (OCR).

Apex Timing ne propose ni API ni port local pour recuperer le timer. Cette application capture la zone d'ecran ou le timer est affiche, extrait le texte par OCR, et le rend disponible pour un affichage externe.

## Fonctionnalites

- Selection de la fenetre Apex Timing parmi les fenetres ouvertes
- Definition visuelle de la zone du timer (rectangle a dessiner)
- Extraction OCR en continu (intervalle configurable)
- Preprocessing image (niveaux de gris, binarisation, seuil ajustable)
- Affichage du timer dans l'application
- Fenetre d'affichage externe plein ecran (F11) pour ecran secondaire
- Ecriture du timer dans `timer.txt` (lisible par d'autres applications)
- Log horodate dans `timer_log.txt`
- Configuration sauvegardee entre les sessions (`config.json`)

## Installation (Windows)

1. Copier le dossier sur le PC
2. Double-cliquer **install.bat** (installe Python, Tesseract OCR et les dependances automatiquement via winget)
3. Double-cliquer **run.bat** pour lancer l'application

## Utilisation

1. Selectionner la fenetre Apex Timing dans le menu deroulant
2. Cliquer **Definir la zone** et dessiner un rectangle autour du timer
3. Cliquer **Test OCR** pour verifier la detection
4. Ajuster le **seuil** si la lecture est mauvaise (fond gris / chiffres noirs : ~120-150)
5. Cliquer **Demarrer** pour lancer l'extraction en continu
6. Cliquer **Affichage externe** pour ouvrir le timer sur un second ecran (F11 = plein ecran)

## Sortie

| Fichier | Contenu |
|---|---|
| `timer.txt` | Temps actuel (ecrase a chaque changement) |
| `timer_log.txt` | Historique avec horodatage |

Le fichier `timer.txt` peut etre lu par n'importe quelle application externe (afficheur LCD, serveur web, etc.).

## Stack technique

- Python 3.12
- Tesseract OCR (via pytesseract)
- Pillow (capture et traitement image)
- OpenCV (preprocessing)
- mss (capture d'ecran rapide)
- pygetwindow (detection des fenetres)
- tkinter (interface graphique)
