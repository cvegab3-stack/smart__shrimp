"use strict";

// Convierte la imagen a JPEG en base64 SIN cambiar su resolución: los píxeles por cm deben seguir siendo los de la
// calibración. Acepta un File o un ImageBitmap ya abierto (no lo cierra).
window.SmartShrimpCapture = {
  async fileAsBase64(source) {
    const image = source instanceof Blob ? await createImageBitmap(source) : source;
    const canvas = document.createElement("canvas");
    canvas.width = image.width; canvas.height = image.height;
    canvas.getContext("2d").drawImage(image, 0, 0); if (source instanceof Blob) image.close?.();
    return canvas.toDataURL("image/jpeg", 0.92).split(",")[1];
  },
  async videoAsBase64(video) {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    return canvas.toDataURL("image/jpeg", 0.82).split(",")[1];
  },
  // Bytes reales de un base64 (sin el relleno "="), para comparar con el máximo antes de enviar.
  base64Bytes(value) { const padding = value.endsWith("==") ? 2 : value.endsWith("=") ? 1 : 0; return Math.floor(value.length * 3 / 4) - padding; },
};
