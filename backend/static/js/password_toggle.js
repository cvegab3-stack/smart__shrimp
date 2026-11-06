"use strict";
// Añade un botón con icono de ojo a TODOS los campos <input type="password"> de la página, para mostrar u ocultar
// lo escrito. Se carga desde base.html: cualquier campo de contraseña nuevo lo recibe sin tocar su plantilla.
// Sin JavaScript el campo sigue funcionando como una contraseña normal.
(() => {
  const SVG = 'viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="2" ' +
              'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"';
  const EYE_OPEN = `<svg class="eye-open" ${SVG}><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/>` +
                   '<circle cx="12" cy="12" r="3"/></svg>';
  const EYE_CLOSED = `<svg class="eye-closed" ${SVG} hidden><path d="M10.6 5.1A9.9 9.9 0 0 1 12 5c6.4 0 10 7 10 7a17.6 ` +
                     "17.6 0 0 1-3.2 4.1M6.6 6.6C3.7 8.5 2 12 2 12s3.6 7 10 7a9.7 9.7 0 0 0 5.4-1.6\"/>" +
                     '<path d="M9.9 9.9a3 3 0 0 0 4.2 4.2M3 3l18 18"/></svg>';

  function enhance(input) {
    if (input.dataset.passwordToggle) return;  // ya tiene ojo
    input.dataset.passwordToggle = "on";
    if (!input.id) input.id = `password-${Math.random().toString(36).slice(2, 9)}`;

    const wrap = document.createElement("div");
    wrap.className = "password-wrap";
    input.replaceWith(wrap);
    wrap.append(input);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "password-toggle";
    button.setAttribute("aria-controls", input.id);
    button.innerHTML = EYE_OPEN + EYE_CLOSED;
    wrap.append(button);

    const render = (visible) => {
      const label = visible ? "Ocultar contraseña" : "Mostrar contraseña";
      input.type = visible ? "text" : "password";
      // En SVG la propiedad .hidden no existe: se usa el atributo.
      button.querySelector(".eye-open").toggleAttribute("hidden", visible);
      button.querySelector(".eye-closed").toggleAttribute("hidden", !visible);
      button.setAttribute("aria-label", label);
      button.setAttribute("aria-pressed", String(visible));
      button.title = label;
    };
    render(false);
    button.addEventListener("click", () => { render(input.type === "password"); input.focus(); });
    // Al enviar o vaciar el formulario se vuelve a ocultar: el navegador y los gestores de contraseñas ven un campo
    // de contraseña normal, y un formulario reiniciado (p. ej. tras "Crear usuario") no deja el campo en texto.
    input.form?.addEventListener("submit", () => render(false));
    input.form?.addEventListener("reset", () => render(false));
  }

  const scan = (root) => root.querySelectorAll?.('input[type="password"]').forEach(enhance);
  scan(document);
  // Campos creados después por JavaScript (p. ej. "Cambiar contraseña" en la tabla de cuentas) también reciben el ojo.
  new MutationObserver((mutations) => mutations.forEach((m) => m.addedNodes.forEach((node) => {
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.matches('input[type="password"]')) enhance(node); else scan(node);
  }))).observe(document.body, { childList: true, subtree: true });
})();
