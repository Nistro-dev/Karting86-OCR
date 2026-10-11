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
URL du serveur : http://<IP_SERVEUR>:8899/upload
Clé API : <CLE_API>
```

**IMPORTANT** : Demande à l'utilisateur l'IP du serveur et la clé API avant d'uploader.

Utilise curl ou PowerShell pour uploader :

```powershell
# Avec curl
curl -X POST "http://<IP>:8899/upload" -H "X-API-Key: <CLE>" -F "file=@$env:TEMP\apex_backup.zip"

# Ou avec PowerShell si curl n'est pas dispo
$headers = @{ "X-API-Key" = "<CLE>" }
Invoke-RestMethod -Uri "http://<IP>:8899/upload" -Method Post -Headers $headers -InFile "$env:TEMP\apex_backup.zip" -ContentType "multipart/form-data"
```

Si le zip est trop gros (> 500 Mo), découpe en plusieurs uploads :
- D'abord `CENTER.GO` et `BOOKINGS.GO` seuls
- Puis les `DAY*.GO` par lot de 5-10

# Étape 4 : Vérifier

Appelle `GET http://<IP>:8899/files` pour vérifier que le fichier est bien arrivé.

Affiche un résumé : nombre de fichiers copiés, taille totale, confirmation que c'est OK.

# Bonus si le temps le permet

Si il reste du temps, copie aussi :
- Le dossier `C:\ApexTiming\GoKarts\` (le logiciel lui-même, pour référence)
- Les logs : `C:\ApexTiming\GoServer\system.log`
- Tout fichier de config intéressant dans `C:\ApexTiming\`
