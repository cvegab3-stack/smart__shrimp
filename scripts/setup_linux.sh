#!/usr/bin/env bash
# Prepara el entorno en Linux (equivalente de setup_windows.ps1): un único entorno .venv312 (Python 3.12) para
# Django, el servicio de visión y las pruebas.
#   bash scripts/setup_linux.sh               -> PyTorch con CUDA (GPU NVIDIA)
#   SMART_SHRIMP_CPU=1 bash scripts/setup_linux.sh   -> PyTorch solo CPU (sin GPU)
#   PYTHON=/ruta/a/python3.12 bash scripts/setup_linux.sh   -> otro intérprete
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

python_bin="${PYTHON:-python3.12}"
if [ ! -x .venv312/bin/python ]; then
    if ! command -v "$python_bin" >/dev/null 2>&1; then
        echo "No encuentro $python_bin. Instala Python 3.12 (p. ej. sudo apt install python3.12 python3.12-venv)." >&2
        exit 1
    fi
    "$python_bin" -m venv .venv312
fi
[ -f .env ] || cp .env.example .env
py=.venv312/bin/python

"$py" -m pip install --upgrade pip
"$py" -m pip install -e ./contracts
"$py" -m pip install -r backend/requirements/development.txt
"$py" -m pip install -r vision_service/requirements-inference.txt
if [ "${SMART_SHRIMP_CPU:-0}" = "1" ]; then
    echo "SMART_SHRIMP_CPU=1: se mantiene PyTorch solo CPU."
else
    # PyTorch con CUDA para la GPU NVIDIA (sustituye la versión CPU que instala ultralytics).
    "$py" -m pip install --upgrade torch==2.15.0+cu132 torchvision==0.29.2+cu132 \
        --index-url https://download.pytorch.org/whl/cu132
fi
"$py" -c "import torch; print('CUDA disponible:', torch.cuda.is_available())"
echo "Preparación terminada. Sigue README.md (sección Linux)."
