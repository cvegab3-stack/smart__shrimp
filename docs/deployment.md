# Linux y despliegue con Docker

Este documento cubre tres formas de ejecutar SMART SHRIMP fuera de Windows y las reglas de cuentas y sesión que conviene conocer al desplegar.

| Forma | Para qué | Base de datos |
|---|---|---|
| Windows (scripts `.ps1`) | Desarrollo local, ver `README.md` | SQLite |
| [Linux sin Docker](#linux-sin-docker) (scripts `.sh`) | Desarrollo local en Linux | SQLite |
| [Docker](#despliegue-con-docker) (`docker-compose.yml`) | Servidor Linux | PostgreSQL |

## Linux sin Docker

Equivale a los scripts de Windows: un entorno `.venv312`, SQLite en `backend/local.sqlite3` y el servicio de visión en `127.0.0.1:8001`.

Requisitos: Python 3.12 con `venv` (en Ubuntu/Debian: `sudo apt install python3.12 python3.12-venv`) y, para la GPU, el controlador NVIDIA.

```bash
bash scripts/setup_linux.sh                 # primera vez; al final imprime "CUDA disponible: True/False"
bash scripts/run_vision_linux.sh            # terminal 1: servicio de visión (recarga al cambiar el código)
bash scripts/run_django_linux.sh            # terminal 2: Django en http://127.0.0.1:8000
bash scripts/create_admin_linux.sh          # una vez: crea el administrador
```

- Sin GPU: `SMART_SHRIMP_CPU=1 bash scripts/setup_linux.sh` (el análisis funciona, más lento).
- Otro puerto para visión: `bash scripts/run_vision_linux.sh --port 8011` y arranca Django con `VISION_PORT=8011 bash scripts/run_django_linux.sh`.
- Sin recarga automática: `bash scripts/run_vision_linux.sh --no-reload`.
- Los scripts leen el mismo `.env` que Windows (se crea desde `.env.example`).

## Despliegue con Docker

`docker-compose.yml` levanta cuatro contenedores en una red interna:

| Servicio | Imagen | Función |
|---|---|---|
| `db` | `postgres:16-alpine` | Base de datos (volumen `pgdata`) |
| `vision` | `vision_service/Dockerfile` | FastAPI + YOLO con GPU; el modelo `models/detector/best.pt` va dentro de la imagen |
| `django` | `backend/Dockerfile` | Django con gunicorn; migra y copia los estáticos al arrancar |
| `nginx` | `nginx:1.27-alpine` | Único puerto publicado (80, o 80/443 con HTTPS); sirve `/static/` y reenvía el resto a Django |

El servicio de visión, Django y PostgreSQL **no** se publican fuera de Docker. nginx tampoco sirve `media/`: las imágenes de los análisis pasan por Django, que comprueba el permiso del usuario.

### Requisitos del servidor

- Docker Engine con Docker Compose 2.24.4 o posterior.
- Para la GPU: controlador NVIDIA y [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html). Comprobación: `docker run --rm --gpus all ubuntu nvidia-smi`.

### Primer arranque

```bash
cp .env.docker.example .env.docker
# Edita .env.docker: DJANGO_SECRET_KEY, POSTGRES_PASSWORD, VISION_SERVICE_TOKEN_SECRET y DJANGO_ALLOWED_HOSTS.
# Para generar claves:  python3 -c "import secrets; print(secrets.token_urlsafe(50))"
docker compose up -d --build
docker compose exec django python manage.py createsuperuser
```

Abre `http://<IP o nombre del servidor>/` (ese nombre debe estar en `DJANGO_ALLOWED_HOSTS`). `.env.docker` contiene secretos y no se sube a Git.

Comandos habituales:

```bash
docker compose ps                     # estado y salud de los contenedores
docker compose logs -f django vision  # registros
docker compose up -d --build          # actualizar tras cambiar el código o el modelo
docker compose down                   # detener (los volúmenes y los datos se conservan)
```

### Sin GPU

```bash
docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build
```

Construye el servicio de visión con PyTorch solo CPU y no reserva la GPU.

### HTTPS

Con `DJANGO_HTTPS=0` (valor del ejemplo) la aplicación funciona por HTTP. Úsalo **solo en una red local de confianza**: las contraseñas y las cookies de sesión viajan sin cifrar. Además, el navegador solo permite la cámara en `localhost` o por HTTPS, así que para el análisis en vivo desde otro equipo hace falta HTTPS.

Para HTTPS:

1. Copia el certificado y su clave en `infra/nginx/certs/fullchain.pem` y `infra/nginx/certs/privkey.pem` (por ejemplo, de Let's Encrypt). La carpeta no se sube a Git.
2. En `.env.docker` pon `DJANGO_HTTPS=1`.
3. Arranca con la variante HTTPS:

   ```bash
   docker compose -f docker-compose.yml -f docker-compose.https.yml up -d --build
   ```

nginx redirige HTTP a HTTPS y envía HSTS. Django marca las cookies como `Secure` y redirige cualquier petición HTTP.

### Copias de seguridad

Los datos viven en dos volúmenes: `pgdata` (base de datos) y `media` (imágenes de los análisis).

```bash
docker compose exec db sh -c 'pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB"' > respaldo_$(date +%F).sql
docker compose exec -T django tar czf - -C /app/backend media > media_$(date +%F).tgz
```

## Cuentas y sesión

Configurables en `.env` (local) o `.env.docker`:

| Variable | Por defecto | Efecto |
|---|---|---|
| `SESSION_IDLE_MINUTES` | 30 | La sesión se cierra tras estos minutos sin peticiones. Cada carga de página o petición de la aplicación la renueva, incluidos los fotogramas del análisis en vivo. También se cierra al cerrar el navegador. |
| `SESSION_WARNING_SECONDS` | 120 | Antes de vencer, la página muestra un aviso con «Seguir conectado». Al vencer, lleva al acceso con el mensaje «Tu sesión se cerró por inactividad». Las pestañas abiertas comparten el contador. |
| `PASSWORD_MIN_LENGTH` | 8 | Longitud mínima de las contraseñas nuevas. Además, una contraseña no puede ser común, ni tener solo números, ni parecerse al usuario, nombre o correo. Los formularios muestran las reglas y las marcan mientras se escribe; el servidor las vuelve a comprobar al guardar. |

Reglas de la gestión de usuarios (las aplica el servidor, tanto en la pantalla *Usuarios* como en `/admin/`):

- Siempre debe quedar **al menos un administrador activo**: no se puede desactivar, quitar el rol de administrador ni borrar al último.
- Un administrador **no puede desactivarse ni quitarse el rol a sí mismo**. Debe hacerlo otro administrador, para que nadie se quede fuera por error.
- El administrador puede editar el usuario, el nombre, el apellido, el correo y el rol de cualquier cuenta. El nombre de usuario no puede repetirse, sin distinguir mayúsculas. Cada cambio queda en la bitácora (`user.updated`) con los campos modificados.
- Una cuenta desactivada pierde la sesión abierta en su siguiente petición.
