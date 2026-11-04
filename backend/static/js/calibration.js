"use strict";
(() => {
  const calibrationForm = document.querySelector("#calibration-form"); const thresholdForm = document.querySelector("#threshold-form"); if (!calibrationForm && !thresholdForm) return;
  const csrf = () => document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("csrftoken="))?.split("=").slice(1).join("=");
  async function post(url, payload) { const response = await fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() || "" }, body: JSON.stringify(payload) }); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.detail ? JSON.stringify(data.detail) : `Error ${response.status}`); return data; }
  const value = (selector) => { const raw = document.querySelector(selector).value.trim(); return raw === "" ? null : Number(raw); };
  calibrationForm?.addEventListener("submit", async (event) => { event.preventDefault(); const message = document.querySelector("#calibration-message"); const ranges = {};
    ["pequeno", "mediano", "grande"].forEach((category) => { ranges[category] = { min_cm: value(`#${category}-min`), max_cm: value(`#${category}-max`) }; });
    try { const data = await post("/api/calibration/", { reference_length_cm: Number(document.querySelector("#reference-length").value), reference_pixels: Number(document.querySelector("#reference-pixels").value), size_ranges: ranges }); message.textContent = `Calibración v${data.version} guardada. Los análisis previos conservan su versión.`; message.className = "alert alert-success"; window.location.reload(); }
    catch (error) { message.textContent = error.message; message.className = "alert alert-error"; }
  });
  thresholdForm?.addEventListener("submit", async (event) => { event.preventDefault(); const message = document.querySelector("#threshold-message");
    try { await post("/api/thresholds/", { detection_confidence: Number(document.querySelector("#detection-threshold").value), visual_condition_confidence: Number(document.querySelector("#condition-threshold").value) }); message.textContent = "Umbrales guardados."; message.className = "alert alert-success"; }
    catch (error) { message.textContent = error.message; message.className = "alert alert-error"; }
  });
})();
