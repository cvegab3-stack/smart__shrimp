"use strict";
// Lista de reglas bajo cada campo de contraseña nueva (<input data-password-rules="8">, el número es la longitud
// mínima). Se marca mientras se escribe. Solo orienta: el servidor vuelve a aplicar TODAS las reglas al guardar,
// incluidas las que aquí no se pueden comprobar (contraseñas comunes, parecido con los datos de la cuenta).
// Con data-password-confirm="#id" también indica si la confirmación coincide.
(() => {
  function enhance(input) {
    if (input.dataset.passwordRulesReady) return; input.dataset.passwordRulesReady = "on";
    const min = Number(input.dataset.passwordRules) || 8;
    const confirm = input.dataset.passwordConfirm ? document.querySelector(input.dataset.passwordConfirm) : null;
    const rules = [
      { text: `Al menos ${min} caracteres`, test: (v) => v.length >= min },
      { text: "No solo números", test: (v) => v.length > 0 && !/^\d+$/.test(v) },
      { text: "Que no sea común ni se parezca a tu usuario, nombre o correo (se comprueba al guardar)", test: null },
    ];
    if (confirm) rules.push({ text: "Las dos contraseñas coinciden", test: (v) => v.length > 0 && v === confirm.value });
    const list = document.createElement("ul"); list.className = "password-rules"; list.setAttribute("aria-live", "polite");
    const items = rules.map((rule) => { const item = document.createElement("li"); item.textContent = rule.text;
      if (!rule.test) item.classList.add("is-info"); list.append(item); return item; });
    const render = () => rules.forEach((rule, index) => { if (!rule.test) return; const ok = rule.test(input.value);
      items[index].classList.toggle("is-ok", ok); items[index].setAttribute("aria-label", `${rule.text}: ${ok ? "cumple" : "pendiente"}`); });
    // Con data-password-rules-target="#id" la lista va en ese contenedor (p. ej. el recuadro de requisitos de
    // «Crear usuario», en una sola línea); si no, bajo el propio campo.
    const target = input.dataset.passwordRulesTarget ? document.querySelector(input.dataset.passwordRulesTarget) : null;
    if (target) { list.classList.add("password-rules-inline"); target.append(list); }
    else (input.closest(".field") || input.parentElement).append(list);
    input.addEventListener("input", render); confirm?.addEventListener("input", render);
    input.form?.addEventListener("reset", () => setTimeout(render)); render();
  }
  const scan = (root) => root.querySelectorAll?.("input[data-password-rules]").forEach(enhance);
  scan(document);
  // Campos creados después (panel "Cambiar contraseña" de la tabla de cuentas).
  new MutationObserver((mutations) => mutations.forEach((m) => m.addedNodes.forEach((node) => {
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    if (node.matches("input[data-password-rules]")) enhance(node); else scan(node);
  }))).observe(document.body, { childList: true, subtree: true });
})();
