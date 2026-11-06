# SMART SHRIMP

Sistema para contar y medir camarones con una cámara. Tiene dos partes:

- **Django** (puerto 8000): la aplicación web. Ahí están los usuarios, los análisis y el historial.
- **Servicio de visión** (puerto 8001): recibe las imágenes y detecta los camarones con un modelo YOLO.

Para trabajar en tu equipo no necesitas Docker ni PostgreSQL: los datos se guardan en `backend/local.sqlite3`.

## Antes de empezar

- Windows con PowerShell.
- Python 3.12 de [python.org](https://www.python.org/downloads/).
- Una GPU NVIDIA con el controlador al día. Sin GPU también funciona, pero más lento.
- El proyecto en una ruta corta, por ejemplo `C:\smart_shrimp`. Con rutas largas PyTorch se instala pero no carga.

El modelo ya viene en `models/detector/best.pt`. El dataset solo hace falta para entrenar (ver [training/README.md](training/README.md)).

## Instalar y arrancar

La primera vez, prepara el entorno. Tarda un rato y al final debería decir `CUDA disponible: True`:

```powershell
.\scripts\setup_windows.ps1
```

Si PowerShell no te deja ejecutar scripts, corre antes `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`. Solo afecta a esa ventana.

Después abre dos ventanas de PowerShell y déjalas abiertas mientras uses la aplicación:

```powershell
.\scripts\run_vision_windows.ps1   # ventana 1: espera a que diga "Application startup complete."
.\scripts\run_django_windows.ps1   # ventana 2
```

Entra en <http://127.0.0.1:8000>. Para parar, pulsa `Ctrl+C` en cada ventana. Ambos servicios se reinician solos cuando cambias el código.

## Primer uso

1. Crea el administrador con `.\scripts\create_admin_windows.ps1` y entra con esa cuenta.
2. En **Usuarios**, crea al menos un operador. Solo el operador puede hacer análisis.
3. En **Calibración**, indica cuántos píxeles mide una referencia conocida en la cámara, por ejemplo una regla de 10 cm que ocupa 400 px. Sin esto no se puede crear un análisis.
4. Entra como operador, ve a **Nuevo análisis** y elige imagen o cámara en vivo. En vídeo, un camarón se cuenta cuando cruza la línea central.

Los resultados quedan en **Historial**.

Ten en cuenta que el modelo todavía es un piloto. Detecta y cuenta bien, pero aún no clasifica el color ni estima el peso. También puede confundir manos u objetos con camarones, así que apunta la cámara solo a la zona de trabajo. Las métricas están en `models/detector/model_info.json`.

## Cuentas y sesión

- Las contraseñas deben tener al menos 8 caracteres. No se aceptan contraseñas comunes, ni solo números, ni parecidas al nombre de usuario.
- Siempre tiene que quedar un administrador activo, y ningún administrador puede desactivarse a sí mismo.
- Si pasas 30 minutos sin actividad, la sesión se cierra. Te avisa dos minutos antes.

Estos valores se cambian en `.env` (`PASSWORD_MIN_LENGTH`, `SESSION_IDLE_MINUTES`).

## Si algo falla

| Problema | Solución |
|---|---|
| «El servicio de visión no respondió» | La ventana 1 no está abierta o aún está cargando. Espera y pulsa *Reintentar análisis*. |
| *Crear análisis* está desactivado | Falta la calibración (paso 3). |
| No aparece *Nuevo análisis* | Entraste con un usuario que no es operador. |
| La cámara no arranca | Abre la aplicación como `127.0.0.1:8000` y no con la IP de red. Revisa también que ninguna otra app esté usando la cámara. |
| `CUDA disponible: False` | Actualiza el controlador NVIDIA y vuelve a ejecutar el setup. |

## Linux y Docker

En Linux se usan los mismos pasos, pero con los scripts `.sh` (`bash scripts/setup_linux.sh`, etc.). Para montarlo en un servidor con Docker:

```bash
cp .env.docker.example .env.docker   # rellena las claves
docker compose up -d --build
```

Todos los detalles están en [docs/deployment.md](docs/deployment.md).

## Pruebas

```powershell
.\.venv312\Scripts\python.exe -m pytest contracts/tests backend/apps tests_integration vision_service/tests
```

## Llevarlo a otro equipo

`.\scripts\package_windows.ps1` crea un ZIP con lo necesario. No incluye el entorno, el dataset, `.env` ni la base de datos. En el otro equipo, descomprímelo en una ruta corta, ejecuta el setup y cambia las claves de `.env`.

## Carpetas

- `backend/`: la aplicación Django (cuentas, análisis, resultados).
- `vision_service/`: el servicio de detección.
- `models/detector/`: el modelo que usa la aplicación.
- `training/`: scripts para entrenar el modelo.
- `contracts/`: datos compartidos entre Django y el servicio de visión.
- `scripts/`: arranque en Windows y Linux.
- `docs/`: despliegue y trazabilidad de requisitos ([traceability.md](docs/traceability.md)).
