"use strict";
(() => {
  const form = document.querySelector("#report-create-form"); if (!form) return; const message = document.querySelector("#report-message");
  form.addEventListener("submit", async (event) => { event.preventDefault();
    try {
      const data = await window.SmartShrimp.request("/api/reports/", { method: "POST", body: { date_from: document.querySelector("#report-from").value, date_to: document.querySelector("#report-to").value } });
      message.textContent = `Reporte creado para ${data.summary.shrimp_count} camarones. El peso se muestra como valor estimado.`; message.className = "alert alert-success"; window.location.reload();
    } catch (error) { message.textContent = error.message; message.className = "alert alert-error"; }
  });
})();
