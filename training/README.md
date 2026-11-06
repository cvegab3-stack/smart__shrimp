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

Resultado del modelo actual (`best.pt`, SHA-256 `98112a05…`) obtenido el 04-11-2026 con 347 imágenes y 697 objetos:

| Métrica | Valor |
|---|---|
| mAP50 | 0,894 |
| mAP50-95 | 0,785 |
| Precision / recall (Ultralytics) | 0,937 / 0,791 |
| Conf 0,5: precision / recall | 0,978 / 0,704 (TP 491, FP 11, FN 206) |
| Conf 0,5: conteo exacto / error medio de conteo | 55,6 % de imágenes / 0,57 camarones por imagen |

Coinciden con las cifras `test_old` de `models/detector/model_info.json`.

Límites:

- Este test solo cubre la plataforma original (2 sesiones). El `test_new` de `shrimp_combined_v2` (40 imágenes de superficies secas) no se ha reproducido aquí, porque ese dataset no está en este equipo.
- Ultralytics reescribe `labels.cache` en la carpeta del dataset y, la primera vez, descarga la fuente `Arial.ttf` a `%APPDATA%\Ultralytics`.

Hallazgos, limitaciones y atributos aprovechables: [docs/dataset_shrimp_roboflow_v4.md](../docs/dataset_shrimp_roboflow_v4.md).
Origen y licencia de cada fuente: `registry/sources.yaml`.

Este dataset **no** aporta longitud en cm, peso, frescura ni presentación. Además, solo muestra una plataforma oscura y seca, por lo que no hay evidencia de funcionamiento sobre otras superficies.

Los scripts `build_dataset.py`, `split_dataset.py`, `export_model.py`, `s3_sync.py` y `train_color_classifier.py` siguen siendo plantillas (solo un comentario). `evaluate_detector.py`, `evaluate_test_split.py` y `build_combined_dataset.py` sí están implementados.
