$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
. (Join-Path $PSScriptRoot "Import-LocalEnv.ps1")
Import-SmartShrimpEnv -ProjectRoot $projectRoot
$env:PYTHONPATH = (Join-Path $projectRoot "backend")
& (Join-Path $projectRoot ".venv312\Scripts\python.exe") .\backend\manage.py createsuperuser
