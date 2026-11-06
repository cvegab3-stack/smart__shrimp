#!/usr/bin/env bash
# Crea la cuenta de administrador en la base local (equivalente de create_admin_windows.ps1).
# Con Docker usa en su lugar: docker compose exec django python manage.py createsuperuser
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"
# shellcheck source=scripts/load_env.sh
source scripts/load_env.sh
load_smart_shrimp_env "$root"
export PYTHONPATH="$root/backend"
exec "$root/.venv312/bin/python" backend/manage.py createsuperuser
