function Import-SmartShrimpEnv {
    param([Parameter(Mandatory = $true)][string]$ProjectRoot)

    $envFile = Join-Path $ProjectRoot ".env"
    if (-not (Test-Path -LiteralPath $envFile)) {
        throw "No existe .env. Ejecuta primero .\scripts\setup_windows.ps1 desde la raíz del proyecto."
    }
    foreach ($line in Get-Content -LiteralPath $envFile) {
        if ($line -match '^\s*#' -or $line -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') { continue }
        [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2].Trim(), "Process")
    }
    $env:DJANGO_SETTINGS_MODULE = "config.settings.local"
    $env:VISION_SERVICE_URL = "http://127.0.0.1:8001"
}
