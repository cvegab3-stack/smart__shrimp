# Arranca el servicio de visión (M3) en local.
#   .\scripts\run_vision_windows.ps1              -> puerto 8001, se recarga solo al cambiar su código
#   .\scripts\run_vision_windows.ps1 -NoReload    -> sin recarga automática (arranque único, p. ej. demostraciones)
#   .\scripts\run_vision_windows.ps1 -Port 8011   -> otro puerto (Django usa VISION_SERVICE_URL de .env)
# La recarga vigila vision_service\app y contracts: al guardar un cambio, uvicorn reinicia el servicio y vuelve a
# cargar el modelo en la GPU (unos segundos). Así nunca queda ejecutándose código antiguo sin que nadie lo note.
param(
    [int]$Port = 8001,
    [switch]$NoReload
)

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
$visionDir = Join-Path $projectRoot "vision_service"
$contractsDir = Join-Path $projectRoot "contracts"
$env:PYTHONPATH = $visionDir + ";" + $contractsDir

$arguments = @("-m", "uvicorn", "app.main:app", "--app-dir", $visionDir, "--host", "127.0.0.1", "--port", $Port)
if (-not $NoReload) {
    $arguments += @("--reload", "--reload-dir", (Join-Path $visionDir "app"), "--reload-dir", $contractsDir)
    Write-Host "Recarga automática activada: al cambiar el código del servicio de visión se reinicia solo."
}
& $pythonExe @arguments
