#!/bin/sh
# Arranque del contenedor de Django: migraciones y archivos estáticos antes del servidor.
# DJANGO_MIGRATE_ON_START=0 desactiva las migraciones automáticas (p. ej. con varias réplicas: migrar una sola vez).
set -eu
if [ "${DJANGO_MIGRATE_ON_START:-1}" = "1" ]; then
    python manage.py migrate --noinput
fi
# Copia los estáticos al volumen que comparte con nginx (nginx los sirve sin pasar por Django).
python manage.py collectstatic --noinput --verbosity 0
exec "$@"
