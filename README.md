# SMART SHRIMP

Aplicación Django para usuarios, análisis e historial. El servicio de visión (FastAPI, "M3") procesa los fotogramas con el detector YOLO entrenado en la GPU. En desarrollo local, Django guarda los datos en SQLite (`backend/local.sqlite3`) y se comunica con M3 por `http://127.0.0.1:8001`. No hace falta Docker ni PostgreSQL.

Todo (Django, servicio de visión y pruebas) usa **un solo entorno: `.venv312`** (Python 3.12 con PyTorch CUDA).

## Requisitos

- Windows con PowerShell.
- Python 3.12 instalado desde [python.org](https://www.python.org/downloads/) (incluye el lanzador `py`).
- GPU NVIDIA con su controlador actualizado (probado con RTX 3050 Laptop, CUDA 13.2). Sin GPU, el servicio funciona en CPU, pero más lento.
- El modelo del detector en `models/detector/best.pt` (incluido con el código; origen, SHA-256 y métricas en `models/detector/model_info.json`). La aplicación **no necesita el dataset**: solo hace falta para entrenar (ver [training/README.md](training/README.md)).
- Una ruta corta para el proyecto (máximo 120 caracteres), por ejemplo `C:\smart_shrimp`. Windows limita las rutas a 260 caracteres y PyTorch instala archivos con nombres muy largos; con una ruta larga, la instalación termina pero PyTorch no carga.

Si PowerShell impide ejecutar los scripts, ejecuta una vez en esa ventana (solo afecta a esa ventana):

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## 1. Preparar el entorno (solo la primera vez)

Abre PowerShell en la carpeta del proyecto:

```powershell
.\scripts\setup_windows.ps1
```

Crea `.venv312` si no existe, copia `.env.example` a `.env` si falta e instala Django, Ultralytics y PyTorch CUDA. Al final debe imprimir `CUDA disponible: True`.

Comprobación manual de la GPU:

```powershell
.\.venv312\Scripts\python.exe -c "import torch; print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
```

## 2. Arrancar la aplicación (dos ventanas de PowerShell)

**Ventana 1: servicio de visión.**

```powershell
.\scripts\run_vision_windows.ps1
```

Espera a ver `Application startup complete.` y `Uvicorn running on http://127.0.0.1:8001`. Al arrancar se carga el modelo en la GPU (unos segundos); hasta entonces Django no puede analizar.

**Ventana 2: Django.**

```powershell
.\scripts\run_django_windows.ps1
```

Aplica las migraciones y abre la aplicación en [http://127.0.0.1:8000](http://127.0.0.1:8000).

Deja ambas ventanas abiertas mientras uses la aplicación. Para detener un servicio, pulsa `Ctrl+C` en su ventana. Si cambias código del servicio de visión, reinícialo (Django se recarga solo).

## 3. Configurar (una vez, como administrador)

Si aún no hay cuenta de administrador, créala en otra ventana:

```powershell
.\scripts\create_admin_windows.ps1
```

Inicia sesión como administrador y:

1. **Usuarios**: crea al menos un usuario con rol **operador**. Solo el operador puede crear análisis y ver *Nuevo análisis*.
2. **Calibración y umbrales**:
   - *Calibración*: medida de referencia en cm y su equivalente en píxeles en la imagen de la cámara (por ejemplo, una regla de 10 cm que ocupa 400 px). Esto convierte el tamaño de las cajas en longitudes en cm.
   - *Umbrales* (se crean automáticamente con 0.5 y 0.5; puedes cambiarlos): **confianza mínima de detección** (recomendado `0.5`; por debajo aumentan los falsos positivos) y **confianza mínima de condición visual** (por ejemplo `0.5`).

Sin umbrales guardados, crear un análisis falla con «No hay umbrales de confianza configurados».

## 4. Probar con imágenes y vídeo reales (como operador)

Cierra sesión e inicia sesión con el usuario operador. Ve a **Nuevo análisis**, escribe un código de lote y elige el origen:

- **Imagen**: *Crear análisis* → *Seleccionar imagen* → *Analizar imagen*. Se envía la imagen, se detectan los camarones y se guardan los resultados. Para probar puedes usar imágenes de `shrimp_roboflow_v4/detect_grouped_reviewed_v1/images/` dentro de la carpeta del dataset (`..\dataset`, junto al proyecto), si la tienes en este equipo.
- **Video en tiempo real**: *Crear análisis* → *Iniciar cámara* (acepta el permiso del navegador) → cuando termines, *Detener y finalizar*. Se envían hasta 15 fotogramas por segundo; el **conteo** sube cuando un camarón cruza la línea vertical del centro de la imagen.

Los resultados quedan en **Historial**.

Qué esperar del modelo actual (piloto):

- Detecta y cuenta camarones (una clase, `camaron`).
- La condición visual sale como `no_concluyente` y el peso como no disponible: aún no hay clasificador de color ni regresor de peso.
- Las longitudes en cm solo son reales si la calibración se hizo con una referencia medida en la misma cámara.
- **Falsos positivos fuera del montaje de captura**: el modelo se entrenó solo con imágenes que tenían camarones (ninguna escena vacía), así que puede marcar personas, manos u objetos como camarón. Apunta la cámara solo a la zona de camarones. En vídeo, un objeto debe mantenerse 3 fotogramas para contarse (`VIDEO_MIN_TRACK_HITS`) y se descartan cajas mayores al 45 % de la imagen (`MAX_BOX_AREA_RATIO`). La solución definitiva es reentrenar añadiendo fotos de la cámara real sin camarones.
- Es un piloto: validación mAP50-95 ≈ 0,94, sin evaluar test y con casos de etiquetas pendientes. No tomes sus cifras como definitivas.

## Problemas frecuentes

| Mensaje o síntoma | Causa y solución |
|---|---|
| «No hay umbrales de confianza configurados» | El administrador debe guardar los umbrales (paso 3). |
| «El servicio de visión no respondió después de los reintentos configurados» | La ventana 1 no está abierta o no terminó de arrancar. Arráncala y espera a `Application startup complete.`; luego usa *Reintentar análisis*. |
| Acceso denegado en *Nuevo análisis* | Has entrado con un usuario que no es operador. |
| El botón *Crear análisis* está desactivado | No hay calibración vigente (paso 3). |
| «No se pudo iniciar la cámara» | Permiso de cámara denegado, o la cámara está en uso por otra aplicación. Abre la aplicación como `http://127.0.0.1:8000` (no por IP de red) para que el navegador permita la cámara. |
| `No se encontraron los pesos entrenados` al arrancar visión | Falta `models/detector/best.pt`, o `DETECTOR_WEIGHTS` en `.env` apunta a un archivo inexistente. |
| `CUDA disponible: False` | Vuelve a ejecutar el setup o el comando de PyTorch CUDA; comprueba el controlador NVIDIA. |

## Pruebas automáticas

Desde la raíz:

```powershell
& .\.venv312\Scripts\python.exe -m pytest contracts/tests backend/apps/accounts/tests backend/apps/analysis/tests backend/apps/results/tests tests_integration vision_service/tests
```

Consulta [docs/traceability.md](docs/traceability.md) para el mapa RF/RNF y las validaciones pendientes.

## Modelo conectado

`scripts/run_vision_windows.ps1` comprueba que existan `.venv312` y los pesos, y arranca M3 en `127.0.0.1:8001`. Usa `models/detector/best.pt`, salvo que `.env` defina otro archivo en `DETECTOR_WEIGHTS`. El modelo se precarga al iniciar para que el primer fotograma no supere el tiempo límite de Django (`VISION_TIMEOUT_SECONDS=5`).

`models/detector/best.pt` es una copia de `training/runs/detector/camaron_v2_combined_dry_r2/weights/best.pt` (mismo SHA-256; ver `models/detector/model_info.json`). El modelo anterior está respaldado en `models/detector/backup/`. Para entrenar o reentrenar el detector, consulta [training/README.md](training/README.md).

## Compartir o llevar a otro equipo

Lo necesario es el código, `models/detector/` y las dependencias declaradas (`backend/requirements/`, `vision_service/requirements*.txt`, `contracts/`). **No** se llevan `.venv312` (≈3,8 GB, no es portable), el dataset, `training/runs/`, las cachés, `.env` (contiene secretos) ni `backend/local.sqlite3` (datos locales). Todo eso está en `.gitignore`.

Para crear un ZIP con solo lo necesario (lo deja junto a la carpeta del proyecto):

```powershell
.\scripts\package_windows.ps1
```

En el otro equipo:

1. Descomprime en una ruta corta, por ejemplo `C:\smart_shrimp`.
2. Instala Python 3.12 y el controlador NVIDIA (ver Requisitos).
3. Ejecuta `.\scripts\setup_windows.ps1`: crea un `.venv312` nuevo, copia `.env.example` a `.env` e instala las dependencias. Cambia en `.env` las claves `DJANGO_SECRET_KEY` y `VISION_SERVICE_TOKEN_SECRET`.
4. Sigue los pasos 2 y 3 de este documento (la base de datos se crea vacía; vuelve a crear el administrador, los usuarios y la calibración).

El dataset solo hace falta si vas a entrenar en ese equipo: copia la carpeta `dataset` junto a la carpeta del proyecto (por ejemplo `C:\smart_shrimp` y `C:\dataset`), o define `SMART_SHRIMP_DATA_DIR` con su ruta.

## Mapa de carpetas

- `backend/apps/accounts`: cuatro roles, login, bloqueo y bitácora.
- `backend/apps/analysis`: sesiones, calibración, umbrales y estados.
- `backend/apps/results`: persistencia atómica, historial y reportes.
- `backend/integrations/vision_client.py`: único cliente de M3.
- `vision_service`: API protegida de detección, seguimiento y conteo con el modelo YOLO.
- `contracts`: catálogo y mensajes compartidos.
- `models/detector`: modelo YOLO que usa la aplicación y sus metadatos.
- `training`: preparación del dataset y entrenamiento del detector. El dataset vive fuera del código, en `..\dataset` (junto a la carpeta del proyecto).
