#!/usr/bin/env bash
# Arranca el servicio de visión (M3) en local en Linux (equivalente de run_vision_windows.ps1).
#   bash scripts/run_vision_linux.sh                 -> puerto 8001, se recarga solo al cambiar su código
#   bash scripts/run_vision_linux.sh --no-reload     -> sin recarga automática (p. ej. demostraciones)
#   bash scripts/run_vision_linux.sh --port 8011     -> otro puerto (arranca Django con VISION_PORT=8011)
set -euo pipefail
port=8001
reload=1
while [ $# -gt 0 ]; do
    case "$1" in
        --port) port="$2"; shift 2 ;;
        --no-reload) reload=0; shift ;;
        *) echo "Opción desconocida: $1 (usa --port N o --no-reload)" >&2; exit 2 ;;
    esac
done

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
# shellcheck source=scripts/load_env.sh
source scripts/load_env.sh
load_smart_shrimp_env "$root"

# Modelo de la aplicación: models/detector/best.pt, salvo que .env defina DETECTOR_WEIGHTS. No usa el dataset.
weights="${DETECTOR_WEIGHTS:-$root/models/detector/best.pt}"
py="$root/.venv312/bin/python"
[ -f "$weights" ] || { echo "No se encontraron los pesos entrenados: $weights" >&2; exit 1; }
[ -x "$py" ] || { echo "No existe .venv312. Ejecuta primero bash scripts/setup_linux.sh" >&2; exit 1; }
export DETECTOR_WEIGHTS="$weights"
export PYTHONPATH="$root/vision_service:$root/contracts"

args=(-m uvicorn app.main:app --app-dir "$root/vision_service" --host 127.0.0.1 --port "$port")
if [ "$reload" = "1" ]; then
    args+=(--reload --reload-dir "$root/vision_service/app" --reload-dir "$root/contracts")
    echo "Recarga automática activada: al cambiar el código del servicio de visión se reinicia solo."
fi
exec "$py" "${args[@]}"
