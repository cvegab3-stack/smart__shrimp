"""Validación de la imagen que llega del navegador, antes de gastar un intento en el servicio de visión.

El navegador convierte siempre la foto a JPEG; se admite también PNG. Se comprueba lo que realmente se envía:
que sea base64, que sea una imagen (firma), que no pase del tamaño máximo y, si la cabecera lo permite, que no sea
demasiado pequeña para medir. Las dimensiones se leen de la cabecera, sin decodificar la imagen entera.
"""

import base64
import binascii
import struct

from django.conf import settings

JPEG_SIGNATURE = b"\xff\xd8\xff"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Marcadores SOF de JPEG que llevan alto y ancho (todos los SOFn salvo DHT, JPG y DAC).
_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


class InvalidImage(ValueError):
    """La imagen no se puede usar; el mensaje es apto para el operador."""


def image_size(data: bytes) -> tuple[int, int] | None:
    """(ancho, alto) leídos de la cabecera PNG o JPEG; None si no se encuentran."""
    if data.startswith(PNG_SIGNATURE) and len(data) >= 24 and data[12:16] == b"IHDR":
        return struct.unpack(">II", data[16:24])
    if not data.startswith(JPEG_SIGNATURE):
        return None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            return None
        marker = data[index + 1]
        if marker == 0xFF:  # relleno entre marcadores
            index += 1
            continue
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:  # marcadores sin longitud
            index += 2
            continue
        length = struct.unpack(">H", data[index + 2:index + 4])[0]
        if marker in _JPEG_SOF:
            height, width = struct.unpack(">HH", data[index + 5:index + 9])
            return width, height
        if marker == 0xDA:  # empiezan los datos de la imagen: ya no hay cabecera
            return None
        index += 2 + length
    return None


def validate_image_base64(value: str) -> bytes:
    """Devuelve los bytes de la imagen o lanza InvalidImage con un motivo claro."""
    try:
        data = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidImage("La imagen llegó dañada. Vuelve a elegir la foto y analízala de nuevo.") from exc
    if not data:
        raise InvalidImage("La imagen está vacía. Elige otra foto.")
    if not data.startswith((JPEG_SIGNATURE, PNG_SIGNATURE)):
        raise InvalidImage("El archivo enviado no es una imagen JPG o PNG. Elige otra foto.")
    max_mb = settings.ANALYSIS_MAX_IMAGE_MB
    if len(data) > max_mb * 1024 * 1024:
        weight = f"{len(data) / 1024 / 1024:.1f}".replace(".", ",")
        raise InvalidImage(f"La imagen pesa {weight} MB y el máximo es {max_mb:g} MB. Usa una foto más liviana.")
    size = image_size(data)
    min_side = settings.ANALYSIS_MIN_IMAGE_SIDE
    if size is not None and min(size) < min_side:
        raise InvalidImage(f"La imagen mide {size[0]} × {size[1]} px: es demasiado pequeña para medir camarones "
                           f"(mínimo {min_side} px por lado). Usa una foto de la cámara de análisis.")
    return data
