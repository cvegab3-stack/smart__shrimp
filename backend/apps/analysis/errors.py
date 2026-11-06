"""Catálogo único de errores del flujo de análisis.

Cada error pertenece a una de tres clases, y la clase decide qué pasa con el análisis y qué se le ofrece a quien lo ve:

- ENTRADA: el problema es el archivo o el dato enviado. El análisis NO cambia de estado; se corrige y se reenvía.
- TRANSITORIO: falla momentánea del servicio o de la red. El análisis pasa a "con error" y reintentar lo resuelve.
- CONFIGURACIÓN: reintentar no sirve hasta que el administrador corrija algo. El análisis pasa a "con error".

Cada código tiene dos textos: uno para el operador en el momento (qué hacer ahora) y otro para quien revisa el lote
después en el historial, el detalle o los reportes (qué pasó). Ningún texto menciona componentes internos.
"""

from dataclasses import dataclass

INPUT = "entrada"
TRANSIENT = "transitorio"
CONFIGURATION = "configuracion"


@dataclass(frozen=True)
class FlowError:
    code: str
    kind: str
    operator_text: str
    record_text: str

    @property
    def retryable(self) -> bool:
        """Solo los errores que dejan el análisis "con error" se reintentan (los de entrada se corrigen y reenvían)."""
        return self.kind != INPUT


_ADMIN = "Avisa al administrador; cuando lo corrija, pulsa «Reintentar»."

CATALOG = {item.code: item for item in (
    FlowError("invalid_image", INPUT,
              "No se pudo usar esta imagen. Elige otra foto JPG, PNG o WEBP y vuelve a analizar.",
              "La imagen enviada no se pudo leer."),
    FlowError("vision_unavailable", TRANSIENT,
              "El servicio de análisis no responde en este momento. El lote quedó guardado: espera unos segundos "
              "y pulsa «Reintentar».",
              "El servicio de análisis no respondió."),
    FlowError("vision_session_lost", TRANSIENT,
              "El servicio de análisis se reinició y perdió este intento. Pulsa «Reintentar» para empezarlo de nuevo.",
              "El servicio de análisis se reinició durante el procesamiento."),
    FlowError("interrupted", TRANSIENT,
              "Este análisis quedó sin terminar (se cerró la página o pasó mucho tiempo sin actividad). Pulsa "
              "«Reintentar» para hacerlo de nuevo.",
              "El análisis quedó sin terminar: se interrumpió antes de finalizar."),
    FlowError("vision_misconfigured", CONFIGURATION,
              f"El servicio de análisis no está bien configurado. {_ADMIN}",
              "El servicio de análisis no está bien configurado."),
    FlowError("vision_invalid_response", CONFIGURATION,
              f"El servicio de análisis devolvió un resultado no válido y no se guardó nada. {_ADMIN}",
              "El servicio de análisis devolvió un resultado no válido; no se guardaron resultados."),
)}

# Códigos de versiones anteriores, para que los lotes ya guardados también se lean en lenguaje claro.
LEGACY_CODES = {"vision_summary_error": "vision_invalid_response"}

UNKNOWN = FlowError("unknown", TRANSIENT,
                    "Ocurrió un error inesperado. Pulsa «Reintentar»; si se repite, avisa al administrador.",
                    "Ocurrió un error inesperado durante el análisis.")

CONFIGURATION_CODES = tuple(code for code, item in CATALOG.items() if item.kind == CONFIGURATION) + tuple(
    old for old, new in LEGACY_CODES.items() if CATALOG[new].kind == CONFIGURATION)


def get_error(code: str | None) -> FlowError:
    """Devuelve la entrada del catálogo (o una genérica si el código no existe)."""
    code = LEGACY_CODES.get(code or "", code or "")
    return CATALOG.get(code, UNKNOWN)


def describe(code: str | None) -> dict:
    """Datos del error listos para la API: clase, si se puede reintentar y los dos textos."""
    if not code:
        return {"error_kind": "", "retryable": False, "operator_message": "", "error_text": ""}
    error = get_error(code)
    return {"error_kind": error.kind, "retryable": error.retryable,
            "operator_message": error.operator_text, "error_text": error.record_text}
