"use strict";
// Vencimiento de sesión por inactividad. Django cierra la sesión tras SESSION_IDLE_MINUTES sin peticiones (cada
// petición la renueva). Esta página lleva la misma cuenta: cada petición propia (carga de página o fetch) reinicia
// el contador; unos minutos antes muestra un aviso con "Seguir conectado" y, al llegar a cero, lleva al acceso.
// Escribir en un formulario sin enviarlo NO renueva la sesión en el servidor, por eso tampoco reinicia el contador.
// Varias pestañas comparten la última actividad (localStorage): trabajar en una no hace vencer a las demás.
(() => {
  const body = document.body;
  const idleMs = Number(body.dataset.sessionIdle) * 1000; if (!idleMs) return;
  const warnMs = Math.min(Number(body.dataset.sessionWarning) * 1000 || 120000, idleMs / 2);
  const loginUrl = body.dataset.loginUrl; const keepaliveUrl = body.dataset.keepaliveUrl; const logoutUrl = body.dataset.logoutUrl;
  const KEY = "smartShrimp.lastActivity";
  let last = Date.now(); let leaving = false; let dialog = null;
  const shared = () => { try { return Number(localStorage.getItem(KEY)) || 0; } catch { return 0; } };
  const mark = () => { last = Date.now(); try { localStorage.setItem(KEY, String(last)); } catch { /* sin almacenamiento */ } hide(); };
  const expire = () => { if (leaving) return; leaving = true; window.location.assign(`${loginUrl}?expired=1`); };

  // Toda petición al propio servidor cuenta como actividad; un 401 significa que la sesión ya venció.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const response = await nativeFetch(input, init);
    let sameOrigin = true; try { sameOrigin = new URL(input instanceof Request ? input.url : String(input), location.href).origin === location.origin; } catch { /* URL relativa rara: se asume propia */ }
    if (sameOrigin) { if (response.status === 401) expire(); else mark(); }
    return response;
  };

  function build() {
    dialog = document.createElement("div"); dialog.className = "session-warning"; dialog.setAttribute("role", "alertdialog");
    dialog.setAttribute("aria-labelledby", "session-warning-title"); dialog.setAttribute("aria-describedby", "session-warning-text");
    const title = document.createElement("h2"); title.id = "session-warning-title"; title.textContent = "Tu sesión está por vencer";
    const text = document.createElement("p"); text.id = "session-warning-text";
    const actions = document.createElement("div"); actions.className = "session-warning-actions";
    const stay = document.createElement("button"); stay.type = "button"; stay.className = "btn btn-teal"; stay.textContent = "Seguir conectado";
    const leave = document.createElement("a"); leave.className = "btn btn-secondary"; leave.href = logoutUrl; leave.textContent = "Cerrar sesión";
    stay.addEventListener("click", async () => { stay.disabled = true;
      // Un 401 lo atiende el envoltorio de fetch (lleva al acceso); aquí solo queda el fallo de red.
      try { await window.SmartShrimp.request(keepaliveUrl, { method: "POST" }); }
      catch (error) { if (error.status !== 401) text.textContent = "No se pudo contactar al servidor. Revisa la conexión e inténtalo de nuevo."; }
      finally { stay.disabled = false; } });
    actions.append(stay, leave); dialog.append(title, text, actions); body.append(dialog); dialog.hidden = true;
  }
  function show(remainingMs) {
    if (!dialog) build();
    const seconds = Math.ceil(remainingMs / 1000); const clock = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
    dialog.querySelector("p").textContent = `Por inactividad, se cerrará en ${clock}. Pulsa "Seguir conectado" para continuar.`;
    if (dialog.hidden) { dialog.hidden = false; dialog.querySelector("button").focus(); }
  }
  function hide() { if (dialog && !dialog.hidden) dialog.hidden = true; }
  function tick() {
    const remaining = idleMs - (Date.now() - Math.max(last, shared()));
    if (remaining <= 0) expire(); else if (remaining <= warnMs) show(remaining); else hide();
  }
  // Otra pestaña renovó la sesión: se oculta el aviso aquí también.
  window.addEventListener("storage", (event) => { if (event.key === KEY) tick(); });
  // Los navegadores frenan los temporizadores de pestañas ocultas: al volver se recalcula enseguida.
  document.addEventListener("visibilitychange", () => { if (!document.hidden) tick(); });
  mark(); setInterval(tick, 1000);
})();
