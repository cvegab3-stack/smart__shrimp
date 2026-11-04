$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot
. (Join-Path $PSScriptRoot "Import-LocalEnv.ps1")
Import-SmartShrimpEnv -ProjectRoot $projectRoot

# Modelo de la aplicación: models\detector\best.pt, salvo que .env defina DETECTOR_WEIGHTS. No usa el dataset.
$weightsPath = if ($env:DETECTOR_WEIGHTS) { $env:DETECTOR_WEIGHTS } else { Join-Path $projectRoot "models\detector\best.pt" }
$pythonExe = Join-Path $projectRoot ".venv312\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $weightsPath)) {
    throw "No se encontraron los pesos entrenados: $weightsPath"
}
if (-not (Test-Path -LiteralPath $pythonExe)) {
    throw "No se encontró Python CUDA del entorno .venv312: $pythonExe"
}

$env:DETECTOR_WEIGHTS = $weightsPath
$env:PYTHONPATH = (Join-Path $projectRoot "vision_service") + ";" + (Join-Path $projectRoot "contracts")
& $pythonExe -m uvicorn app.main:app --app-dir (Join-Path $projectRoot "vision_service") --host 127.0.0.1 --port 8001
