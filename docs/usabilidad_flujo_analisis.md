# Pruebas de usabilidad del flujo de análisis

Guía para medir, con usuarios reales de planta, si el flujo de análisis se entiende y se recupera bien de los errores. Se aplica **dos veces**: una línea base antes de los cambios y otra después, con las mismas tareas, para comparar.

## Qué se evalúa

| Perfil | Parte del flujo que usa | Participantes |
|---|---|---|
| Operador | Crear el análisis, capturar (imagen o video), reintentar, finalizar | 5 |
| Control de calidad | Encontrar lotes en el historial y entender qué pasó con cada uno | 2–3 |
| Supervisor | Generar el reporte del período e interpretar la salud del flujo | 2–3 |
| Administrador | Calibrar con una foto y detectar fallas del servicio de análisis | 1–2 |

Con 5 operadores aparecen la mayoría de los problemas de uso. Los demás perfiles hacen tareas más cortas.

## Preparación

- **Lugar y equipo**: la planta, con el computador o tableta y la cámara que usan a diario. No se hace en una oficina con otro equipo.
- **Datos**: calibración vigente y algunos lotes ya cargados (finalizados, con error e interrumpidos) para las tareas de revisión.
- **Archivos de prueba**: una foto buena de la cámara de análisis, una foto HEIC o GIF, una foto de otra cámara (con otra resolución) y un archivo dañado.
- **Fallo controlado**: para la tarea del servicio caído, el facilitador detiene el servicio de visión (`docker compose stop vision`) en el momento indicado y lo vuelve a iniciar cuando el participante lo pida o tras 2 minutos.
- **Roles**: un facilitador, que lee las tareas y no ayuda, y un observador, que toma tiempos y notas.

## Cómo se conduce cada sesión

1. Explicar que se evalúa el sistema, no a la persona, y pedir que piense en voz alta.
2. Leer cada tarea tal cual está escrita, sin decir dónde hacer clic.
3. No ayudar. Si la persona lleva más de 3 minutos atascada, se marca la tarea como **no completada** y se pasa a la siguiente.
4. Al final, aplicar el cuestionario SUS y hacer una pregunta abierta: *«¿Qué fue lo más confuso?»*.

## Tareas

### Operador

| # | Tarea (leer al participante) | Éxito si… |
|---|---|---|
| O1 | «Analiza el lote LOTE-PRUEBA-01 con esta foto.» | Ve los resultados del lote |
| O2 | «Analiza el lote LOTE-PRUEBA-02 con esta otra foto.» (archivo HEIC o dañado) | Entiende que el archivo no sirve, elige la foto buena y termina |
| O3 | «Analiza el lote LOTE-PRUEBA-03.» (el facilitador detiene el servicio justo antes de pulsar «Analizar») | Pulsa «Reintentar» cuando el servicio vuelve y termina sin elegir la foto otra vez |
| O4 | «Analiza el lote LOTE-PRUEBA-04 con video.» | Inicia la cámara, espera al primer fotograma, finaliza y ve resultados |
| O5 | «Analiza tres lotes seguidos: LOTE-A, LOTE-B y LOTE-C.» | Los tres terminan sin recargar la página |
| O6 | «Ayer quedó un lote con error. Termínalo.» | Lo encuentra en «Mis lotes», pulsa «Reintentar» y lo completa |

### Control de calidad

| # | Tarea | Éxito si… |
|---|---|---|
| C1 | «Muéstrame los lotes que fallaron esta semana.» | Usa el filtro de estado «Con error» |
| C2 | «Abre uno y explícame por qué falló y qué debería hacerse.» | Explica la causa con sus palabras y si el operador puede reintentarlo |

### Supervisor

| # | Tarea | Éxito si… |
|---|---|---|
| S1 | «Genera el reporte de la semana pasada.» | El reporte aparece en la lista al primer intento |
| S2 | «Según ese reporte, ¿cuántos análisis fallaron y por qué?» | Lee el bloque «Salud del flujo» y las causas de error |

### Administrador

| # | Tarea | Éxito si… |
|---|---|---|
| A1 | «Registra la calibración con esta foto de la regla.» (primero una foto demasiado pequeña, después la correcta) | Entiende el rechazo y calibra con la foto correcta |
| A2 | «¿Está funcionando el servicio de análisis?» (con el servicio detenido) | Lo ve en el panel sin que nadie se lo diga |
| A3 | «¿Hay lotes que fallaron por algo que tengas que corregir tú?» | Encuentra «Errores de configuración» en el panel |

## Qué se mide

| Métrica | Cómo se registra | Meta |
|---|---|---|
| Tasa de éxito | Tareas completadas sin ayuda ÷ tareas | ≥ 90 % |
| Tiempo por tarea | Desde que se lee la tarea hasta el éxito | O1 < 1 min; O5 < 3 min |
| Tiempo de recuperación | En O2, O3 y O6: desde que aparece el error hasta retomar el flujo | < 30 s |
| Errores de uso | Clics en botones que no correspondían, recargas, preguntas al facilitador | Tendencia a la baja entre línea base y después |
| SUS | Cuestionario de 10 preguntas al final | ≥ 70 |

### Cuestionario SUS

Cada pregunta se responde de 1 (muy en desacuerdo) a 5 (muy de acuerdo):

1. Creo que me gustaría usar este sistema con frecuencia.
2. Encontré el sistema innecesariamente complejo.
3. Pensé que el sistema era fácil de usar.
4. Creo que necesitaría ayuda de una persona técnica para poder usarlo.
5. Las funciones del sistema estaban bien integradas.
6. Había demasiada inconsistencia en el sistema.
7. Imagino que la mayoría de la gente aprendería a usarlo muy rápido.
8. Encontré el sistema muy incómodo de usar.
9. Me sentí muy seguro al usar el sistema.
10. Necesité aprender muchas cosas antes de poder usarlo.

**Puntaje**: en las preguntas impares se resta 1 a la respuesta; en las pares, se resta la respuesta a 5. Se suman los 10 valores y el total se multiplica por 2,5. El resultado va de 0 a 100.

## Registro de resultados

Guardar en `docs/evidence/usabilidad/` un archivo por ronda (`linea_base_AAAA-MM-DD.md` y `despues_AAAA-MM-DD.md`) con esta tabla por participante:

| Participante | Perfil | Tarea | ¿Éxito? | Tiempo | Errores de uso | Observaciones (citas textuales) |
|---|---|---|---|---|---|---|

Al final de cada ronda, agregar:

- El SUS promedio por perfil.
- Los **3 problemas más graves**, cada uno con la tarea donde apareció y cuántos participantes lo sufrieron.
- La comparación con la ronda anterior: qué mejoró, qué empeoró y qué sigue igual.

## Qué cubre ya la prueba automática

Antes de la prueba con personas, el flujo se recorrió en un navegador real (Chromium con cámara simulada y el servicio de visión fallando a propósito) en 11 escenarios: validación de cada tipo de archivo, reintento reutilizando la imagen, imagen ilegible, servicio caído al crear y al analizar, sesión perdida al finalizar, video con falla en vivo, reintento desde «Mis lotes», revisión por control de calidad, reporte del supervisor y panel del administrador. Esa prueba confirma que **funciona**. La prueba con personas mide si **se entiende**.
