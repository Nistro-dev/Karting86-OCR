# Mission

Tu es sur le **PC de la piste de karting** (Windows). Tu dois copier TOUTES les bases de données Firebird d'Apex Timing et les uploader sur un serveur distant.

**C'est URGENT** — le PC s'éteint dans 15 minutes. Fais tout le plus vite possible, sans poser de questions.

# Étape 1 : Trouver les fichiers

Les bases de données sont dans `C:\ApexTiming\Data\`. Ce sont des fichiers `.GO` :
- `DAY<YYYYMMDD>.GO` — une base par jour (ex: `DAY20261011.GO`)
- `CENTER.GO` — paramètres globaux
- `CENTERHIST.GO` — historique
- `BOOKINGS.GO` — réservations
- Et tout autre fichier `.GO` présent

# Étape 2 : Lister et zipper

```powershell
# Lister tous les .GO avec leur taille
Get-ChildItem "C:\ApexTiming\Data\*.GO" | Select-Object Name, Length, LastWriteTime | Format-Table

# Tout zipper en un seul fichier
Compress-Archive -Path "C:\ApexTiming\Data\*.GO" -DestinationPath "$env:TEMP\apex_backup.zip" -Force
```

Affiche la liste des fichiers trouvés et la taille du zip.

# Étape 3 : Uploader

Upload le zip vers le serveur :

```
URL du serveur : https://claudepistekarting.codeforgestudio.fr/upload
```

La clé API est : `e56fe007baf11bee8dde93603cc0ee534dccd6ecb81fc54f70f4e603630e49c9`

**Ne pose AUCUNE question, fais tout directement.**

Utilise curl pour uploader :

```powershell
curl -X POST "https://claudepistekarting.codeforgestudio.fr/upload" -H "X-API-Key: e56fe007baf11bee8dde93603cc0ee534dccd6ecb81fc54f70f4e603630e49c9" -F "file=@$env:TEMP\apex_backup.zip"
```

Si le zip est trop gros (> 500 Mo), découpe en plusieurs uploads :
- D'abord `CENTER.GO` et `BOOKINGS.GO` seuls
- Puis les `DAY*.GO` par lot de 5-10

# Étape 4 : Vérifier

Appelle `GET https://claudepistekarting.codeforgestudio.fr/files` pour vérifier que le fichier est bien arrivé (pas besoin de clé API pour la lecture).

Affiche un résumé : nombre de fichiers copiés, taille totale, confirmation que c'est OK.

# Bonus si le temps le permet

Si il reste du temps, copie aussi :
- Le dossier `C:\ApexTiming\GoKarts\` (le logiciel lui-même, pour référence)
- Les logs : `C:\ApexTiming\GoServer\system.log`
- Tout fichier de config intéressant dans `C:\ApexTiming\`
