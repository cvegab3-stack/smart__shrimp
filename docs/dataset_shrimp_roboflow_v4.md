# Dataset `shrimp_roboflow_v4`: auditoría y uso (fase 1)

Fuente: [shrimp-object-tracking-and-counting v4](https://universe.roboflow.com/espol-magof/shrimp-object-tracking-and-counting/dataset/4),
workspace `espol-magof` en Roboflow Universe, **licencia MIT**. Conservar esta atribución en cualquier redistribución o publicación de resultados.

ZIP auditado: `shrimp-object-tracking-and-counting.v4-final_version.yolov8.zip`
(SHA-256 `683e314edb05703888c7eb04d71013c0fc764204da443f6f06c978f478c9bde4`). El ZIP no se modifica.

## Cómo regenerarlo

```powershell
& .\.venv312\Scripts\python.exe training\scripts\prepare_shrimp_dataset.py `
    --zip "C:\Users\JOHN\Downloads\shrimp-object-tracking-and-counting.v4-final_version.yolov8.zip"
```

Por defecto escribe en `..\dataset\shrimp_roboflow_v4` (la carpeta `dataset` junto al proyecto, fuera del código) (`--output` o `SMART_SHRIMP_DATA_DIR` lo cambian). Añada `--overwrite` para regenerar una salida anterior y `--audit-only` para no copiar imágenes. Requiere `numpy>=2`, `Pillow` y `PyYAML` (ya en `.venv312`). Tarda unos 2 minutos.

Salida (fuera del código e ignorada por git):

| Ruta | Contenido |
|---|---|
| `shrimp_roboflow_v4/audit/audit_report.md` | Informe completo: qué se verificó y qué queda pendiente |
| `audit/audit.json` | Mismos resultados en formato máquina |
| `audit/class_map.json` | Las 12 clases originales con tamaño, cabeza, cola y candidato de `integridad` |
| `audit/objects.csv` | Un objeto por fila: clase original, atributos, geometría y avisos. `label_line` coincide con la línea del `.txt` generado |
| `audit/images.csv` | Inventario por imagen: origen, hash, estado de etiqueta y segmentación, grupo y partición |
| `audit/sources_and_groups.csv` | Imagen fuente → sesión (grupo) → partición agrupada |
| `audit/near_duplicates.csv` | Pares casi duplicados (informativo) |
| `audit/review/` | Hojas de revisión visual (cuadro verde, polígono cian) con `index.csv` |
| `detect/` | Detección, 1 clase `camaron`: `data_grouped.yaml` (usar) y `data_original_split.yaml` (con fuga) |
| `segment/` | Segmentación, 1 clase: solo imágenes con todos sus objetos en polígonos válidos |

## Resultados de la auditoría automática

- ZIP íntegro (CRC correcto). No hay rutas inseguras, nombres repetidos ni archivos fuera de estructura.
- Hay 8.085 imágenes JPEG de 640×360 y todas se decodifican. Provienen de **3.378 imágenes fuente**, porque cada fuente de train aparece en 3 variantes aumentadas por Roboflow.
- Hay **9.032 objetos**: 8.084 polígonos y 948 cuadros. Las 12 clases están presentes en las tres particiones originales.
- Un objeto tiene un cuadro degenerado (<1 px) y su imagen se excluye. Hay 8 objetos diminutos (<4 px), conservados y señalados.
- Hay 14 etiquetas vacías: 8 en train, 3 en valid y 3 en test.
- Hay 10 grupos de imágenes idénticas por hash, todos dentro de la misma partición.
- Segmentación: 7.209 imágenes con todos los polígonos válidos, 858 solo con cuadros, 3 mixtas (excluidas de segmentación) y 15 no aplicables.
- Conjuntos generados:
  - Detección: 8.070 imágenes y 9.030 objetos.
  - Segmentación: 7.209 imágenes y 8.079 objetos.

### Fuga en la partición original

- 12 de 13 vídeos tienen fotogramas en más de una partición.
- 517 de 866 segundos de captura aparecen en varias particiones.
- Prácticamente todas las imágenes de valid y test tienen una imagen de train tomada a ≤ 1 s.

Las métricas con la partición original estarán **sobreestimadas**. `data_original_split.yaml` existe solo para comparar.

### Partición agrupada

Se unen en un mismo grupo:

- los fotogramas del mismo vídeo;
- las capturas separadas por ≤ 60 s (cada vídeo se trata como un intervalo supuesto de 180 s);
- las imágenes idénticas;
- los pares casi idénticos (dHash 256 bits ≤ 8).

El resultado son **14 sesiones** en 2 días (11-03-2023 y 14-03-2023). Se asignan sesiones completas:

| Partición | Sesiones | Fuentes | Imágenes (detección) | Objetos |
|---|---|---|---|---|
| train | 9 | 2.530 | 6.035 | 6.460 |
| valid | 3 | 501 | 499 | 589 |
| test | 2 | 347 | 347 | 477 |

Verificación independiente:

- Separación mínima entre particiones: 64 s (train-valid), 80 s (train-test) y 113 s (valid-test).
- Ningún vídeo ni imagen idéntica compartidos entre particiones.
- Ningún casi-duplicado ≤ 8 bits entre particiones.

En valid/test se usa una variante por fuente para no triplicar el peso de las fuentes que provienen de la antigua train.

Limitaciones de esta partición:

- **Cada sesión contiene casi una sola clase** (p. ej., una sesión es 96 % `pequeno-sincabeza-concola`). La asignación elige las sesiones de valid/test que cubren los 3 tamaños y los 4 estados de cabeza/cola, pero no puede incluir las 12 clases sin fuga. Sirve para evaluar la detección de `camaron`, no para comparar métricas por clase.
- Con 14 grupos la varianza de las métricas es alta.
- No se puede saber, a partir de los metadatos, si los mismos ejemplares se reutilizaron entre sesiones.
- Las imágenes de valid/test que venían de la antigua train son variantes aumentadas (rotación o desenfoque).
- La duración de los vídeos es un supuesto (`--video-span-seconds`).

## Hallazgos de la inspección manual inicial (03-11-2026)

Se revisaron las hojas de `audit/review/`: una muestra aleatoria de 60 imágenes y las 14 de etiqueta vacía, además de dos pares de casi-duplicados entre sesiones.

1. **Camarones visibles sin anotar.** Aparecen en ≈25 % de la muestra (15/60) de forma clara y hasta ≈37 % contando casos dudosos de borde u oclusión. El dataset parece anotar un camarón "objetivo" por imagen, no todos los visibles. Consecuencias:
   - un detector entrenado así tenderá a ignorar camarones reales, lo que es crítico para el **conteo**;
   - las métricas penalizarán detecciones correctas como falsos positivos.
2. **Las 14 imágenes con etiqueta vacía contienen camarones.** No son negativas. Por eso se excluyen y `--include-empty` no debe usarse con este ZIP.
3. **Imágenes compuestas.** Hay recortes rectangulares de camarón pegados sobre el fondo, frecuentes en la muestra. El borde del parche puede convertirse en un atajo visual para el modelo.
4. **Objetos distractores sin clase**: memorias USB, anillos, cinta, tarjetas SD, tornillos y llaves. Son útiles como fondo difícil, pero no hay clase `no_camaron`.
5. **Escena única.** Siempre aparece la misma plataforma oscura con rieles metálicos y la misma cámara, con manchas húmedas sobre la superficie. **No hay evidencia** de que el modelo funcione sobre otras superficies, iluminaciones o cámaras.
6. Los casi-duplicados que unían sesiones distintas (11–16 bits) eran **camarones diferentes** sobre el mismo fondo. Por eso se usa un umbral de unión estricto (8 bits).
7. Los polígonos revisados se ajustan bien al contorno, y su conversión a cuadros es correcta.

## Qué se puede aprovechar y qué no

| Atributo | Estado |
|---|---|
| Detección `camaron` (cuadros) | Utilizable con las limitaciones anteriores; requiere completar anotaciones para conteo fiable |
| Máscara de contorno | Polígonos para 7.209 imágenes (`segment/`). Base para medir longitud por contorno en lugar del lado mayor del cuadro, aún no implementado |
| Cabeza / cola visibles | Recuperable por objeto desde `audit/objects.csv` y `class_map.json`. Candidato para `integridad`; validar coherencia antes de usar |
| Tamaño grande/mediano/pequeño | Categoría visual del anotador, **no** longitud. No sustituye la calibración en cm |
| Longitud en cm | **No disponible**: no hay escala ni referencia. Requiere imágenes con patrón de calibración y medidas reales |
| Peso | **No disponible**: requiere pesajes reales asociados a cada ejemplar |
| Frescura / condición visual | **No disponible**: requiere etiquetas de expertos (fresco, intermedio, deteriorado) |
| Presentación (con cáscara/pelado) | **No disponible** |
| `no_camaron` | **No disponible**: los distractores no están anotados |
| Otras superficies o agua | **No representado**: hay que capturar imágenes reales en los materiales de destino |

## Entrenar el detector (no ejecutado en esta fase)

Necesita `ultralytics` (`vision_service/requirements-inference.txt`) y unos pesos iniciales **locales**. El script no descarga nada.

```powershell
& .\.venv312\Scripts\python.exe -m pip install -r vision_service\requirements-inference.txt
& .\.venv312\Scripts\python.exe training\scripts\train_detector.py --model C:\ruta\local\yolov8n.pt --dry-run
& .\.venv312\Scripts\python.exe training\scripts\train_detector.py --model C:\ruta\local\yolov8n.pt
```

Sin pesos preentrenados se puede usar `--model yolov8n.yaml` (desde cero, peor con estos datos).

El modelo esperado queda en `training/runs/detector/camaron_v1/weights/best.pt`. Su única clase es `camaron`, la misma que acepta `vision_service/app/pipeline/detector.py`. Para usarlo en la aplicación se copia a `models/detector/best.pt` y se actualiza `models/detector/model_info.json` (ver [training/README.md](../training/README.md)). El modelo actual se entrenó con `detect_grouped_reviewed_v1`, el dataset por defecto de `training/configs/detector_train.yaml`.

## Siguientes pasos recomendados

1. Reanotar de forma exhaustiva, al menos valid y test de la partición agrupada, todos los camarones visibles. Después medir la tasa real de omisiones.
2. Decidir el tratamiento de las imágenes compuestas: excluirlas, o anotar el borde como fondo.
3. Capturar imágenes reales en las superficies y cámaras de destino, con referencia de calibración y, si se quiere peso o frescura, sus mediciones y etiquetas.
4. Solo entonces comparar métricas y decidir si se usan máscaras para medir longitud.
