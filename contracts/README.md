## Contratos compartidos

El paquete `shrimp_contracts` define el catálogo, el mensaje de fotograma, el resumen final y el token de servicio usado entre Django y M3. El navegador no recibe el token.

El catálogo está en `shrimp_contracts/class_catalog.yaml`. Integridad, presentación y condición visual son grupos independientes. `no_concluyente` expresa baja confianza y no es clase entrenable.

El token usa HMAC-SHA256, identifica emisor y audiencia, lleva identificador único y expira en un máximo de cinco minutos. En desarrollo se configura mediante `VISION_SERVICE_TOKEN_SECRET`; no se debe reutilizar la clave de ejemplo fuera del entorno local.

Instalación editable desde la raíz del repositorio: `python -m pip install -e ./contracts`. Ejecución de pruebas: `python -m pytest contracts/tests`.
