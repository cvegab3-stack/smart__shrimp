"use strict";
// Genera un reporte del período. Valida las fechas antes de enviar, evita el doble envío y, al terminar, recarga la
// lista con ?creado= para que el aviso de éxito se vea (antes se borraba al recargar).
(() => {
  const form = document.querySelector("#report-create-form"); if (!form) return;
  const message = document.querySelector("#report-message"); const submit = document.querySelector("#report-submit");
  const from = document.querySelector("#report-from"); const to = document.querySelector("#report-to");
  const say = (text, ok) => { message.textContent = text; message.className = `alert ${ok ? "alert-success" : "alert-error"}`; };
  // Cada fecha limita a la otra en el selector, para no poder elegir un período al revés.
  from.addEventListener("change", () => { to.min = from.value; }); to.addEventListener("change", () => { from.max = to.value; });
  form.addEventListener("submit", async (event) => { event.preventDefault(); if (submit.disabled) return;
    if (!from.value || !to.value) { say("Elige las fechas «Desde» y «Hasta».", false); return; }
    if (from.value > to.value) { say("La fecha «Desde» debe ser anterior o igual a «Hasta».", false); return; }
    submit.disabled = true; submit.textContent = "Generando…";
    try {
      const data = await window.SmartShrimp.request("/api/reports/", { method: "POST", body: { date_from: from.value, date_to: to.value }, labels: { date_from: "Desde", date_to: "Hasta" } });
      window.location.assign(`?creado=${encodeURIComponent(data.id)}`);
    } catch (error) { say(error.message, false); submit.disabled = false; submit.textContent = "Generar reporte"; }
  });
})();
