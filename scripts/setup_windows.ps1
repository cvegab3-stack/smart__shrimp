$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

# Un único entorno, .venv312 (Python 3.12), para Django, el servicio de visión con GPU y las pruebas.
$pythonExe = Join-Path $projectRoot ".venv312\Scripts\python.exe"

# Windows limita las rutas a 260 caracteres y PyTorch trae DLL con rutas muy largas dentro de .venv312.
if ($projectRoot.Length -gt 120) {
    throw "La ruta del proyecto es demasiado larga ($($projectRoot.Length) caracteres): $projectRoot`nMuévelo a una carpeta más corta, por ejemplo C:\smart_shrimp, y vuelve a ejecutar este script."
}

# pip escribe avisos en stderr; solo se considera fallo un código de salida distinto de 0.
# Sin bloque param: así argumentos como "-e" o "-m" llegan intactos al ejecutable.
function Invoke-Native {
    $exe, $arguments = $args
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { throw "No se encontró el ejecutable: $exe" }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $exe @arguments
    $code = $LASTEXITCODE
    $ErrorActionPreference = $previous
    if ($code -ne 0) { throw "Falló: $exe $($arguments -join ' ') (código $code)" }
}

if (-not (Test-Path -LiteralPath $pythonExe)) {
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        throw "No encuentro el lanzador 'py'. Instala Python 3.12 desde python.org."
    }
    Invoke-Native py -3.12 -m venv .venv312
}
if (-not (Test-Path -LiteralPath ".env")) {
    Copy-Item .env.example .env
}
Invoke-Native $pythonExe -m pip install --upgrade pip
Invoke-Native $pythonExe -m pip install -e .\contracts
Invoke-Native $pythonExe -m pip install -r .\backend\requirements\development.txt
Invoke-Native $pythonExe -m pip install -r .\vision_service\requirements-inference.txt
# PyTorch con CUDA para la GPU NVIDIA (sustituye la versión CPU que instala ultralytics).
Invoke-Native $pythonExe -m pip install --upgrade torch==2.15.0+cu132 torchvision==0.29.2+cu132 --index-url https://download.pytorch.org/whl/cu132
Invoke-Native $pythonExe -c "import torch; print('CUDA disponible:', torch.cuda.is_available())"
Write-Host "Preparación terminada. Sigue README.md." -ForegroundColor Green
