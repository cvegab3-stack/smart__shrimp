#!/usr/bin/env bash
# Arranca Django en local en Linux (equivalente de run_django_windows.ps1): migra y abre http://127.0.0.1:8000.
#   bash scripts/run_django_linux.sh
#   DJANGO_PORT=8010 bash scripts/run_django_linux.sh
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
# shellcheck source=scripts/load_env.sh
source scripts/load_env.sh
load_smart_shrimp_env "$root"
export PYTHONPATH="$root/backend"
py="$root/.venv312/bin/python"
[ -x "$py" ] || { echo "No existe .venv312. Ejecuta primero bash scripts/setup_linux.sh" >&2; exit 1; }
"$py" backend/manage.py migrate
exec "$py" backend/manage.py runserver "127.0.0.1:${DJANGO_PORT:-8000}"
