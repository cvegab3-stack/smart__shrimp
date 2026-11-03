## Servicio de visión

FastAPI atiende las solicitudes internas de Django en `/v1`. Todas las rutas requieren `Authorization: Bearer` con token firmado por Django. No tiene credenciales ni conexión a PostgreSQL.

En Windows, inicie el servicio de inferencia real con `scripts/run_vision_windows.ps1`. El lanzador usa `.venv312`, carga los pesos de `training/runs/detector/shrimp_reviewed_pilot_gpu/weights/best.pt` y requiere `VISION_SERVICE_TOKEN_SECRET` en `.env`.

La detección, el seguimiento y el conteo funcionan con el detector YOLO. Mientras `COLOR_MODEL_PATH` no esté configurado, la condición visual queda como `no_concluyente`; si falta `WEIGHT_MODEL_PATH`, el peso queda nulo. La longitud utiliza la referencia del análisis y la categoría usa los rangos versionados.

Los identificadores de seguimiento y sus votos viven en memoria del proceso. M3 no guarda resultados; Django solicita el resumen y los persiste de manera atómica. Reiniciar M3 elimina las sesiones activas.

Pruebas: `python -m pytest vision_service/tests`. No se publican métricas de exactitud o rendimiento sin dataset y evaluación propios.
