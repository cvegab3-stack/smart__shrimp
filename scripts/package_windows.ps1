param([string]$Output = "")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot

# ZIP para compartir: código, models\detector y dependencias declaradas. Sin entorno, dataset, ejecuciones,
# cachés, .env (secretos) ni la base de datos local.
if (-not $Output) { $Output = Join-Path (Split-Path -Parent $projectRoot) "smart_shrimp_share.zip" }
if (Test-Path -LiteralPath $Output) { throw "Ya existe $Output; bórralo o indica otro -Output." }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot "models\detector\best.pt"))) {
    throw "Falta models\detector\best.pt: el paquete no tendría modelo."
}

$staging = Join-Path ([IO.Path]::GetTempPath()) ("smart_shrimp_share_" + [guid]::NewGuid().ToString("N"))
$excludeDirs = @(".venv312", ".venv", "datasets", "runs", "media", "__pycache__", ".pytest_cache", ".ruff_cache",
                 "smart_shrimp_contracts.egg-info", ".ipynb_checkpoints")
$excludeFiles = @(".env", "local.sqlite3", "*.pyc", "*.cache", "last.pt")
robocopy $projectRoot (Join-Path $staging "smart_shrimp") /E /NFL /NDL /NJH /NJS /NP /XD @excludeDirs /XF @excludeFiles | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy falló (código $LASTEXITCODE)." }
try {
    Compress-Archive -Path (Join-Path $staging "smart_shrimp") -DestinationPath $Output
} finally {
    Remove-Item -LiteralPath $staging -Recurse -Force
}
$size = (Get-Item -LiteralPath $Output).Length / 1MB
Write-Host ("Paquete creado: {0} ({1:N1} MB)" -f $Output, $size) -ForegroundColor Green
exit 0  # robocopy devuelve 1 cuando copia archivos con éxito
