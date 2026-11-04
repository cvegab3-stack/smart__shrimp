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

4. **Publicar el modelo en la aplicación.** El resultado queda en `training/runs/detector/<name>/weights/best.pt`. Si sus métricas son mejores, guarde una copia del modelo anterior, copie el nuevo a `models/detector/best.pt` y actualice `models/detector/model_info.json` (SHA-256 con `Get-FileHash`, ejecución de origen y métricas).

Hallazgos, limitaciones y atributos aprovechables: [docs/dataset_shrimp_roboflow_v4.md](../docs/dataset_shrimp_roboflow_v4.md).
Origen y licencia de cada fuente: `registry/sources.yaml`.

Este dataset **no** aporta longitud en cm, peso, frescura ni presentación. Además, solo muestra una plataforma oscura y seca, por lo que no hay evidencia de funcionamiento sobre otras superficies.

Los scripts `build_dataset.py`, `split_dataset.py`, `export_model.py`, `s3_sync.py` y `train_color_classifier.py` siguen siendo plantillas (solo un comentario). `evaluate_detector.py` y `build_combined_dataset.py` sí están implementados.
