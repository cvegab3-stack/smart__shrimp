$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
. (Join-Path $PSScriptRoot "Import-LocalEnv.ps1")
Import-SmartShrimpEnv -ProjectRoot $projectRoot
$env:PYTHONPATH = (Join-Path $projectRoot "backend")
$pythonExe = Join-Path $projectRoot ".venv312\Scripts\python.exe"
& $pythonExe .\backend\manage.py migrate
& $pythonExe .\backend\manage.py runserver 127.0.0.1:8000
