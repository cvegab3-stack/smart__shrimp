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
    if (typeof data?.error_message === "string") return data.error_message;
    if (typeof data?.detail === "string") return data.detail;
    const parts = Object.entries(data || {}).map(([field, value]) => {
      const text = [].concat(value).filter((item) => typeof item === "string").join(" ");
      return text && labels[field] ? `${labels[field]}: ${text}` : text;
    }).filter(Boolean);
    return parts.length ? parts.join(" · ") : `El servidor no pudo completar la operación (HTTP ${status}). Inténtalo de nuevo.`;
  }

  // Devuelve el JSON de la respuesta (null si no tiene cuerpo, p. ej. 204). Si falla, lanza un Error con el texto
  // del servidor; error.status y error.data conservan el código y el cuerpo (p. ej. el análisis que quedó en error).
  async function request(url, { method = "GET", body, labels } = {}) {
    const send = body !== undefined && body !== null;
    const response = await fetch(url, { method, credentials: "same-origin",
      headers: send ? { "Content-Type": "application/json", "X-CSRFToken": csrf() } : { "X-CSRFToken": csrf() },
      body: send ? JSON.stringify(body) : undefined });
    const data = await response.json().catch(() => null);
    if (!response.ok) { const error = new Error(errorText(data, response.status, labels)); error.status = response.status; error.data = data; throw error; }
    return data;
  }

  // Crea un elemento con clase y texto. El texto va siempre por textContent: los datos (nombres de usuario, lotes)
  // nunca se interpretan como HTML.
  function el(tag, className, text) {
    const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node;
  }

  return { csrf, errorText, request, el };
})();
