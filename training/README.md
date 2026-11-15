# training

Flujo de entrenamiento paso a paso

## Dónde está el dataset

El dataset está separado del código y **solo se lee al preparar datos o entrenar**. La aplicación usa `models/detector/best.pt` y funciona aunque el dataset no esté conectado.

Los scripts buscan la carpeta de datos en este orden (`scripts/data_paths.py`):

1. `--data-dir RUTA`;
2. la variable de entorno `SMART_SHRIMP_DATA_DIR`;
3. la carpeta `dataset` **junto al proyecto** (`..\dataset`), ubicación actual;
4. `datasets\` dentro del proyecto (ubicación anterior).

Si no encuentran el dataset, se detienen indicando las rutas comprobadas.

Estructura actual:

```
smart shirimp\
  smart__shrimp-main\            ← código y models\detector\best.pt
  dataset\
    shrimp_roboflow_v4\          ← detect\, segment\, detect_grouped_reviewed_v1\, audit\
```

Las imágenes de `detect/`, `segment/` y `detect_grouped_reviewed_v1/` son enlaces duros (el mismo archivo en las tres carpetas). Si copias el dataset a otro disco, cada copia ocupará espacio por separado. Guarda las fotos nuevas en carpetas propias dentro de `dataset\`, sin mezclarlas con `shrimp_roboflow_v4`.

## Fase 1: detector de una clase `camaron`

1. **Preparar y auditar el dataset** (no modifica el ZIP; escribe en `<carpeta de datos>\shrimp_roboflow_v4`):

   ```powershell
   & .\.venv312\Scripts\python.exe training\scripts\prepare_shrimp_dataset.py `
       --zip "C:\Users\JOHN\Downloads\shrimp-object-tracking-and-counting.v4-final_version.yolov8.zip"
   ```

   Revise `shrimp_roboflow_v4/audit/audit_report.md` y las hojas de `audit/review/`. La copia con etiquetas revisadas se genera con `apply_label_review.py --zip ...`.

2. **Comprobar la configuración** (`configs/detector_train.yaml`, dataset por defecto `shrimp_roboflow_v4/detect_grouped_reviewed_v1`) sin entrenar:

   ```powershell
   & .\.venv312\Scripts\python.exe training\scripts\train_detector.py --model training\weights\yolov8n.pt --dry-run
   ```

3. **Entrenar.** Requiere `vision_service/requirements-inference.txt` y pesos locales; nunca se descargan:

   ```powershell
   & .\.venv312\Scripts\python.exe training\scripts\train_detector.py --model training\weights\yolov8n.pt --name camaron_v2
   ```

   Para **continuar desde el modelo actual** con fotos nuevas, use `--model models\detector\best.pt`.

4. **Evaluar en test** (ver la sección [Evaluar el detector en test](#evaluar-el-detector-en-test)).

5. **Publicar el modelo en la aplicación.** El resultado queda en `training/runs/detector/<name>/weights/best.pt`. Si sus métricas son mejores, guarde una copia del modelo anterior, copie el nuevo a `models/detector/best.pt` y actualice `models/detector/model_info.json` (SHA-256 con `Get-FileHash`, ejecución de origen y métricas).

## Evaluar el detector en test

`scripts/evaluate_test_split.py` evalúa un modelo **solo** en la partición de prueba de un `data.yaml` con `train`, `val` y `test`. Por defecto usa `shrimp_roboflow_v4/detect_grouped_reviewed_v1/data.yaml` y `models/detector/best.pt`. No entrena ni modifica el modelo, y no permite elegir otra partición: validación no se usa como test.

Antes de medir comprueba que ninguna imagen de test comparta con train o val su nombre, su foto fuente, su contenido (SHA-256), su sesión de captura o su vídeo. La sesión y el vídeo salen de `shrimp_roboflow_v4/audit/images.csv`. Si encuentra algo compartido o no puede comprobarlo, se detiene sin evaluar.

Mide lo mismo que `evaluate_detector.py`:

- las métricas de Ultralytics (conf 0.001, iou 0.7, imgsz 640);
- el punto de operación de la aplicación (`--conf`, 0.5 por defecto): TP/FP/FN con IoU ≥ 0.5 y error de conteo.

Guarda `docs/evidence/detector_test/report.json` con las métricas, el SHA-256 del modelo, la huella del conjunto de test y el resultado de la comprobación.

PowerShell, desde la raíz del proyecto (cambie `--data-dir` por la carpeta que contiene `shrimp_roboflow_v4`):

```powershell
# 1. Solo comprobar la separación de test (no carga el modelo; ~1 min)
& .\.venv312\Scripts\python.exe training\scripts\evaluate_test_split.py `
    --data-dir "C:\ruta\a\dataset" --check-only

# 2. Evaluar el modelo actual en test (GPU; use --device cpu si no hay)
& .\.venv312\Scripts\python.exe training\scripts\evaluate_test_split.py `
    --data-dir "C:\ruta\a\dataset"
```

Resultado del modelo actual (`best.pt`, SHA-256 `491b3176…`, entrenamiento `camaron_v4_bandeja`) obtenido el 15-11-2026 con 347 imágenes y 697 objetos, junto al modelo anterior (`c4316113…`, `camaron_v3_baldosa`):

| Métrica | Actual (v4) | Anterior (v3) |
|---|---|---|
| mAP50 | 0,900 | 0,927 |
| mAP50-95 | 0,784 | 0,795 |
| Precision / recall (Ultralytics) | 0,954 / 0,796 | 0,927 / 0,856 |
| Conf 0,5: precision / recall | 0,971 / 0,713 (TP 497, FP 15, FN 200) | 0,981 / 0,753 (TP 525, FP 10, FN 172) |
| Conf 0,5: conteo exacto / error medio de conteo | 56,5 % / 0,55 camarones por imagen | 59,1 % / 0,50 |

En este test (la plataforma original de ESPOL) v4 baja un poco. Se eligió igualmente porque mejora en las condiciones propias del equipo (ver `docs/evidence/detector_v4/comparison.json`, conf 0,5 y NMS 0,5):

| Camarones encontrados | v4 | v3 |
|---|---|---|
| Bandeja de acero, montón de 6 + 1 camarón + bandeja vacía (5 fotos) | 5 de 19 | 0 de 19 |
| Bandeja de acero, 6 separados (3 fotos) | 15 de 18 | 0 de 18 |
| Baldosa, video propio (21 fotogramas) | 203 de 216 | 187 de 216 |
| Superficies secas de internet (`test_new`, 40 fotos) | 80 de 88 | 77 de 88 |

Informes anteriores: `docs/evidence/detector_test/report_v3_camaron_v3_baldosa.json` y `report_v2_camaron_v2_combined_dry_r2.json`; comparación v2/v3 en `docs/evidence/detector_v3/comparison.json`.

Límites:

- Este test solo cubre la plataforma original (2 sesiones). Las fotos propias (`test_bandeja`, `test_baldosa`) y `test_new` se miden aparte con `evaluate_detector.py`.
- En montones encimados sobre la bandeja todavía omite la mayoría de los camarones: faltan fotos de bandeja tomadas con la cámara de trabajo.
- Ultralytics reescribe `labels.cache` en la carpeta del dataset y, la primera vez, descarga la fuente `Arial.ttf` a `%APPDATA%\Ultralytics`.

Hallazgos, limitaciones y atributos aprovechables: [docs/dataset_shrimp_roboflow_v4.md](../docs/dataset_shrimp_roboflow_v4.md).
Origen y licencia de cada fuente: `registry/sources.yaml`.

Este dataset **no** aporta longitud en cm, peso, frescura ni presentación. Además, solo muestra una plataforma oscura y seca, por lo que no hay evidencia de funcionamiento sobre otras superficies.

Los scripts `build_dataset.py`, `split_dataset.py`, `export_model.py`, `s3_sync.py` y `train_color_classifier.py` siguen siendo plantillas (solo un comentario). `evaluate_detector.py`, `evaluate_test_split.py`, `build_combined_dataset.py` y `prelabel_images.py` sí están implementados.

## Fotos nuevas sin etiquetar

`prelabel_images.py` toma un ZIP o una carpeta con fotos y videos, saca un fotograma por segundo de cada video, pre-etiqueta todo con el modelo actual (a 1280 px) y deja una carpeta lista para corregir en Roboflow o LabelImg, con instrucciones en `LEEME.md`:

```powershell
& .\.venv312\Scripts\python.exe training\scripts\prelabel_images.py --zip "..\dataset\fotos.zip" --output "..\dataset\camarones_nuevos_v1"
```

Las pre-etiquetas hay que revisarlas todas antes de entrenar. Con una superficie que el modelo aún no conoce (p. ej. la bandeja de acero) casi todas salen mal: conviene vaciar `labels/` y etiquetar desde cero.

Una vez corregidas, `build_combined_v3.py` y `build_combined_v4.py` muestran cómo sumarlas al dataset anterior separándolas por sesión (train/val/test), nunca foto a foto.
