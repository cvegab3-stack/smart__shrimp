# Trazabilidad de requisitos

Estado de referencia: implementación de desarrollo en este repositorio. “Implementado” significa que existe el flujo en código y sus pruebas funcionales básicas pasan; no implica validación de aceptación con usuarios, modelos entrenados ni infraestructura de producción.

## Requisitos funcionales

| ID | Requisito | Implementación | Evidencia / estado |
|---|---|---|---|
| RF-01 | Autenticación de operadores | `backend/apps/accounts` login Django, hash del framework y sesiones; usuario sin distinguir mayúsculas; aviso de cuenta inactiva solo con contraseña correcta | `backend/apps/accounts/tests` (`InactiveAccountLoginTests`, `UsernameCaseTests`); implementado |
| RF-02 | Usuarios y roles | Usuario propio con roles operador, calidad, supervisor y administrador; cambio de la propia contraseña en Mi perfil y asignación por el administrador, registrados en bitácora (nunca se muestra ni guarda en claro); errores de validación legibles | `backend/apps/accounts/tests` (`PasswordChangeTests`, `UserCreationValidationTests`); implementado |
| RF-03 | Permisos por rol | permisos DRF y vistas HTML restringidas; denegaciones auditadas; el login exige el perfil del rol de la cuenta (`login.role_mismatch`) | `backend/apps/accounts/tests` (`LoginProfileTests`); implementado |
| RF-04 | Registrar análisis | Sesiones UUID, operador, lote, calibración/umbrales congelados y estados | `backend/apps/analysis/tests`; implementado |
| RF-05 | Detectar en imagen/video | M3 recibe fotogramas; detector configurable, navegador usa cámara; recuadros en vivo con el tamaño; la imagen analizada se guarda y se muestra con recuadros en el detalle; primer plano contado con aviso en modo imagen | `vision_service/tests`, `backend/apps/results/tests` (`AnalysisSnapshotAndSummaryTests`); exactitud en test: ver RNF-03 |
| RF-06 | Conteo con seguimiento | Tracker IoU y línea de conteo M3 | `vision_service/tests`; exactitud de conteo con dataset pendiente |
| RF-07 | Medir longitud | Calibración píxel/cm y medición por detección | `vision_service/tests`; precisión de aceptación pendiente |
| RF-08 | Categoría de tamaño | Bandas versionadas sin solapamiento, aplicación por longitud | `backend/apps/analysis/tests`, `vision_service/tests`; implementado |
| RF-09 | Peso aproximado | Estimador configurable y campo nullable rotulado “estimado” | `vision_service/tests`; pesos/modelo y error de aceptación pendientes |
| RF-10 | Condición visual | Etiquetas visuales separadas; clasificador solo con modelo configurado; advertencia visible | `vision_service/tests`; exactitud ≥0.90 pendiente de dataset etiquetado |
| RF-11 | Guardar resultados | Registros por intento con escritura atómica y estado final | `backend/apps/results/tests`; implementado |
| RF-12 | Consultar historial | filtros de lote, fechas, estado/condición, detalle y aislamiento del operador | `backend/apps/results/tests`; implementado |
| RF-13 | Reporte de producción | agregados persistidos por rango de fecha con conteos, tamaños, peso estimado y condición | `backend/apps/results/tests`; implementado |
| RF-14 | Exportar CSV/PDF | exportaciones de informe y detalle, acceso solo supervisor y evento de auditoría | `backend/apps/results/tests`; implementado |
| RF-15 | Configurar calibración | versiones inmutables, referencias históricas y validación de rangos (sin negativos, orden pequeño < mediano < grande, sin huecos, límites compartidos, referencia ≥ 20 px, aviso de escala poco realista); medición de píxeles con dos clics (📏) que registra la resolución; historial con activación de versiones anteriores sin duplicados | `backend/apps/analysis/tests` (`CalibrationRangeValidationTests`, `CalibrationRangeGapTests`, `CalibrationScaleLogicTests`, `CalibrationHistoryTests`, `CalibrationResolutionTests`); implementado |
| RF-16 | Manejar error de análisis | estado/error visible, reintento con nuevo intento y protección contra resultados parciales | `backend/apps/analysis/tests`, `backend/apps/results/tests`; implementado |

## Requisitos no funcionales

| ID | Criterio | Diseño / evidencia | Estado de aceptación |
|---|---|---|---|
| RNF-01 | 1920×1080, p95 ≤2 s en 100 análisis | resolución/fotogramas aceptados por API | Pendiente: medición en hardware y modelo objetivo |
| RNF-02 | vídeo promedio ≥15 FPS durante 5 min | captura del navegador limitada a 15 FPS y canal asíncrono M3 | Pendiente: prueba sostenida de extremo a extremo |
| RNF-03 | mAP50 ≥0.92 | detector YOLO cargable mediante `DETECTOR_WEIGHTS`; evaluación reproducible en test con `training/scripts/evaluate_test_split.py` | **No cumple** con el modelo actual: mAP50 0,894 en test de la plataforma original (347 imágenes, separación comprobada; `docs/evidence/detector_test/report.json`). Pendiente: test de superficies nuevas (`test_new`) y pesos aprobados |
| RNF-04 | errores longitud/peso dentro de umbral con ≥30 muestras | calibración y estimador configurables; valores ausentes no se inventan | Pendiente: muestras medidas y evaluación estadística |
| RNF-05 | hash unidireccional con sal | autenticación y contraseña gestionadas por Django | Implementado por framework; revisar política de despliegue final |
| RNF-06 | cierre tras 30 min inactivo | expiración de sesión y renovación por petición | Implementado; prueba de reloj/producción pendiente |
| RNF-07 | disponibilidad mensual ≥95%, 07:00–19:00 | endpoint de salud Django disponible | Pendiente: operación y medición mensual |
| RNF-08 | 10 sesiones simultáneas, p95 ≤3 s, 10 min | componentes desacoplados, timeout acotado y servicio M3 separado | Pendiente: prueba de carga en infraestructura objetivo |
| RNF-09 | operador completa análisis en ≤3 acciones tras entrenamiento | flujo de cámara, análisis, cierre y resultados en UI | Pendiente: prueba moderada con 10 operadores; el prototipo reportado supera el límite de acciones |
| RNF-10 | actualizar M3 sin cambiar Django | cliente M3 aislado en `backend/integrations/vision_client.py` y contrato compartido | Implementado por diseño; prueba de sustitución de servicio pendiente |
| RNF-11 | conservar 12 meses y respaldo diario verificable | SQLite persiste en `backend/local.sqlite3`; no hay un respaldo diario automatizado en el entorno local | Pendiente: política de retención y tarea de respaldo/restauración operativa |
| RNF-12 | bitácora inmutable de login, análisis y exportación | `AuditEvent` inmutable y eventos de autenticación/análisis/exportación | Implementado; verificación operativa pendiente |
| RNF-13 | despliegue Linux con un comando documentado | `README.md` documenta arranque local directo en Windows | El requisito de despliegue Linux aún no está cubierto |

## Verificación ejecutada

- Suite de contratos, backend, integración y M3: `python -m pytest contracts/tests backend/apps/accounts/tests backend/apps/analysis/tests backend/apps/results/tests tests_integration vision_service/tests`.
- Lint: `python -m ruff check backend contracts tests_integration vision_service`.
- Migraciones/modelos: `python manage.py makemigrations --check --dry-run` y `python manage.py check` con `config.settings.testing`.
- `node --check` para los archivos JavaScript del frontend.
- Exactitud del detector en test (04-11-2026): `training/scripts/evaluate_test_split.py` sobre `shrimp_roboflow_v4/detect_grouped_reviewed_v1` (ver `training/README.md`).
- No se ejecutó carga, restauración de respaldo o prueba de usabilidad.
