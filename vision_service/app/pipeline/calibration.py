"""Conversión calibrada de píxeles a centímetros."""


def pixels_to_cm(length_pixels: float, reference_length_cm: float, reference_pixels: int) -> float:
    """Aplica la escala física registrada para el análisis."""
    if length_pixels < 0 or reference_length_cm <= 0 or reference_pixels <= 0:
        raise ValueError("La medida y la referencia de calibración deben ser válidas.")
    return length_pixels * reference_length_cm / reference_pixels
