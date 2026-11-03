# Programme une sauvegarde quotidienne sur ce poste, sans droits d'administrateur.
# Le fichier de configuration et les sauvegardes restent dans le profil de l'utilisateur, hors du dépôt.
# Usage : powershell -ExecutionPolicy Bypass -File tools\sauvegarde\installer_tache.ps1
$ErrorActionPreference = "Stop"

$backend = (Resolve-Path (Join-Path $PSScriptRoot "..\..\backend")).Path
$python = Join-Path $backend "venv\Scripts\python.exe"
$script = Join-Path $backend "sauvegarde.py"
$dossier = Join-Path $env:USERPROFILE "Fauche-Sauvegardes"
$config = Join-Path $dossier "fauche-sauvegarde.env"
$journal = Join-Path $dossier "journal.txt"

New-Item -ItemType Directory -Force -Path $dossier | Out-Null

if (-not (Test-Path $config)) {
    @"
# Une valeur par ligne, sans guillemets. Ce fichier contient des secrets : ne le partagez pas.
OUTILLAGE_DATABASE_URL=
OUTILLAGE_SECRET_KEY=cle-locale-pour-la-sauvegarde-uniquement-2026
OUTILLAGE_S3_BUCKET=
OUTILLAGE_S3_ENDPOINT=
OUTILLAGE_S3_REGION=eu-west-3
OUTILLAGE_S3_ACCESS_KEY=
OUTILLAGE_S3_SECRET_KEY=
"@ | Set-Content -Path $config -Encoding utf8
}

# Seul le compte Windows courant peut lire le dossier.
icacls $dossier /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" | Out-Null

$commande = "& '$python' -W ignore '$script' --env '$config' --dest '$dossier' *>> '$journal'"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"$commande`"" -WorkingDirectory $backend
$declencheur = New-ScheduledTaskTrigger -Daily -At 12:30
$reglages = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 1)
Register-ScheduledTask -TaskName "Fauche sauvegarde" -Action $action -Trigger $declencheur -Settings $reglages -Description "Sauvegarde quotidienne de la base et des fichiers Fauché" -Force | Out-Null

Write-Host "Tâche créée : chaque jour à 12 h 30, ou au prochain démarrage si le PC était éteint."
Write-Host "Configuration à remplir : $config"
Write-Host "Sauvegardes et journal : $dossier"
