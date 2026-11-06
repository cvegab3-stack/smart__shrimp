# Imagen de Django (gunicorn) para Linux. Se construye desde la raíz del proyecto (necesita contracts/):
#   docker build -f backend/Dockerfile -t smart-shrimp-django .
# La usa docker-compose.yml; la configuración llega por variables de entorno (.env.docker).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production PYTHONPATH=/app/backend

WORKDIR /app
# Dependencias primero: cambiar el código no obliga a reinstalarlas.
COPY contracts/ contracts/
COPY backend/requirements/ backend/requirements/
RUN pip install ./contracts -r backend/requirements/production.txt

COPY backend/ backend/
# Si el repositorio se clonó en Windows, el script puede llegar con fin de línea CRLF: se normaliza.
RUN sed -i 's/\r$//' backend/docker-entrypoint.sh && chmod +x backend/docker-entrypoint.sh \
    && useradd --system --uid 10001 --create-home smartshrimp \
    && mkdir -p backend/media backend/staticfiles && chown -R smartshrimp backend/media backend/staticfiles
USER smartshrimp
WORKDIR /app/backend

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 CMD ["python", "healthcheck.py"]
ENTRYPOINT ["/app/backend/docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "60", \
     "--access-logfile", "-"]
