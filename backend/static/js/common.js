"use strict";
// Utilidades compartidas por todas las páginas (window.SmartShrimp). Se carga en el <head> de base.html, antes que
// los demás scripts. Peticiones a la API de Django con la cookie de sesión y el token CSRF, errores de DRF como
// texto legible y un ayudante para crear elementos sin interpretar HTML.
window.SmartShrimp = (() => {
  const csrf = () => document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("csrftoken="))?.split("=").slice(1).join("=") || "";

  // DRF responde los errores como lista, {detail}, {error_message} o {campo: [mensajes]}. Con `labels`
  // ({campo: "Nombre visible"}) cada mensaje lleva delante el nombre del campo. Nunca devuelve "{}" ni vacío.
  function errorText(data, status, labels = {}) {
    if (Array.isArray(data)) return data.join(" ");
    // En la API de análisis, detail es lo que hay que decirle al operador ahora y error_message lo que pasó (historial).
    if (typeof data?.detail === "string") return data.detail;
    if (typeof data?.error_message === "string" && data.error_message) return data.error_message;
    const parts = Object.entries(data || {}).map(([field, value]) => {
      const text = [].concat(value).filter((item) => typeof item === "string").join(" ");
      return text && labels[field] ? `${labels[field]}: ${text}` : text;
    }).filter(Boolean);
    return parts.length ? parts.join(" · ") : `El servidor no pudo completar la operación (HTTP ${status}). Inténtalo de nuevo.`;
  }

  // Devuelve el JSON de la respuesta (null si no tiene cuerpo, p. ej. 204). Si falla, lanza un Error con el texto
  // del servidor; error.status y error.data conservan el código y el cuerpo (p. ej. el análisis que quedó en error).
  // Sin conexión, error.status es 0 (no llegó respuesta: no se sabe si el servidor recibió la petición).
  async function request(url, { method = "GET", body, labels } = {}) {
    const send = body !== undefined && body !== null;
    let response;
    try {
      response = await fetch(url, { method, credentials: "same-origin",
        headers: send ? { "Content-Type": "application/json", "X-CSRFToken": csrf() } : { "X-CSRFToken": csrf() },
        body: send ? JSON.stringify(body) : undefined });
    } catch {
      const error = new Error("No hay conexión con el servidor. Revisa la red y vuelve a intentarlo."); error.status = 0; error.data = null; throw error;
    }
    const data = await response.json().catch(() => null);
    if (!response.ok) {
      const tooLarge = response.status === 413;
      const error = new Error(tooLarge ? "La imagen es demasiado pesada para enviarla. Usa una foto más liviana." : errorText(data, response.status, labels));
      error.status = response.status; error.data = data; throw error;
    }
    return data;
  }

  // Errores de getUserMedia en lenguaje de planta (el navegador los da en inglés y sin indicar qué hacer).
  function cameraErrorText(error) {
    switch (error?.name) {
      case "NotAllowedError": return "El navegador no tiene permiso para usar la cámara. Permite el acceso (icono junto a la dirección de la página) y vuelve a intentarlo.";
      case "NotFoundError": case "OverconstrainedError": return "No se encontró la cámara elegida. Comprueba que esté conectada o elige otra en la lista.";
      case "NotReadableError": case "AbortError": return "La cámara está en uso por otra aplicación o pestaña. Ciérrala y vuelve a intentarlo.";
      case "SecurityError": return "Este navegador solo permite usar la cámara en una conexión segura (HTTPS).";
      default: return "No se pudo abrir la cámara. Vuelve a intentarlo o recarga la página.";
    }
  }

  // Valida una foto elegida por el usuario antes de usarla. Devuelve { ok, message, bitmap }; si ok, el bitmap
  // queda abierto para medir o enviar (quien lo recibe debe cerrarlo con bitmap.close()).
  const IMAGE_TYPES = ["image/jpeg", "image/png", "image/webp"]; const IMAGE_EXTENSIONS = /\.(jpe?g|png|webp)$/i;
  const MAX_FILE_MB = 40;  // archivo original; lo que se envía se limita después, ya convertido a JPEG
  async function validateImageFile(file, { minSide = 0 } = {}) {
    if (!file) return { ok: false, message: "Elige una imagen." };
    const typeOk = file.type ? IMAGE_TYPES.includes(file.type) : IMAGE_EXTENSIONS.test(file.name);
    if (!typeOk) { const extension = (file.name.split(".").pop() || "").toUpperCase();
      return { ok: false, message: `Formato no compatible${extension ? ` (${extension})` : ""}. Usa una foto JPG, PNG o WEBP.` }; }
    if (!file.size) return { ok: false, message: "El archivo está vacío. Elige otra foto." };
    if (file.size > MAX_FILE_MB * 1024 * 1024) return { ok: false, message: `La foto pesa ${(file.size / 1048576).toFixed(1).replace(".", ",")} MB y el máximo es ${MAX_FILE_MB} MB. Usa una foto más liviana.` };
    let bitmap;
    try { bitmap = await createImageBitmap(file); } catch { return { ok: false, message: "No se pudo abrir la imagen: el archivo puede estar dañado. Prueba con otra foto." }; }
    if (minSide && Math.min(bitmap.width, bitmap.height) < minSide) { const { width, height } = bitmap; bitmap.close?.();
      return { ok: false, message: `La imagen mide ${width} × ${height} px: es demasiado pequeña para medir camarones (mínimo ${minSide} px por lado). Usa una foto de la cámara de análisis.` }; }
    return { ok: true, bitmap };
  }

  // Crea un elemento con clase y texto. El texto va siempre por textContent: los datos (nombres de usuario, lotes)
  // nunca se interpretan como HTML.
  function el(tag, className, text) {
    const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node;
  }

  return { csrf, errorText, request, el, cameraErrorText, validateImageFile };
})();
