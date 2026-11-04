"use strict";
(() => {
  const form = document.querySelector("#report-create-form"); if (!form) return; const message = document.querySelector("#report-message");
  const csrf = () => document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("csrftoken="))?.split("=").slice(1).join("=");
  form.addEventListener("submit", async (event) => { event.preventDefault();
    const response = await fetch("/api/reports/", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() || "" }, body: JSON.stringify({ date_from: document.querySelector("#report-from").value, date_to: document.querySelector("#report-to").value }) });
    const data = await response.json().catch(() => ({})); if (!response.ok) { message.textContent = data.detail || `Error ${response.status}`; message.className = "alert alert-error"; return; }
    message.textContent = `Reporte creado para ${data.summary.shrimp_count} camarones. El peso se muestra como valor estimado.`; message.className = "alert alert-success"; window.location.reload();
  });
})();
