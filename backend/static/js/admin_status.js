"use strict";
// Panel del administrador: indica si el servicio de análisis responde. Se consulta aparte para no frenar el panel.
(() => {
  const dot = document.querySelector("#vision-dot"); const text = document.querySelector("#vision-status"); const refresh = document.querySelector("#vision-refresh");
  if (!dot || !text) return;
  async function check() {
    refresh.disabled = true; text.textContent = "Comprobando…"; dot.className = "service-dot";
    try {
      const { available } = await window.SmartShrimp.request("/api/vision/health/");
      dot.classList.add(available ? "ok" : "down");
      text.textContent = available ? "Disponible" : "No disponible: los análisis fallarán. Revisa que el servicio de visión esté en marcha y que su secreto coincida con el de Django.";
    } catch (error) { dot.classList.add("down"); text.textContent = error.message; }
    finally { refresh.disabled = false; }
  }
  refresh.addEventListener("click", check); check();
})();
