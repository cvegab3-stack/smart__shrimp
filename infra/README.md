# Infraestructura

El desarrollo local de SMART SHRIMP se ejecuta directamente en Windows o Linux con SQLite. Sigue `../README.md`; no requiere contenedores ni PostgreSQL.

Para desplegar en un servidor Linux con Docker (PostgreSQL, servicio de visión con GPU, Django con gunicorn y nginx) usa `../docker-compose.yml` y la sección «Despliegue con Docker» de `../README.md`.

- `nginx/nginx.dev.conf`: nginx por HTTP (lo usa `docker-compose.yml`).
- `nginx/nginx.prod.conf`: nginx por HTTPS con los certificados de `nginx/certs/` (lo usa `docker-compose.https.yml`). La carpeta `certs/` no se sube a Git.
- `aws/`: scripts opcionales; requieren configuración independiente antes de usarse.

Ninguna configuración de nginx publica el servicio de visión ni la carpeta `media/`: las imágenes de los análisis las sirve Django tras comprobar el permiso del usuario.
