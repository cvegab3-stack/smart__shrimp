"use strict";
(() => {
  const form = document.querySelector("#analysis-create-form"); if (!form) return;
  const source = document.querySelector("#source-type"); const imageControls = document.querySelector("#image-controls"); const videoControls = document.querySelector("#video-controls");
  const errorPanel = document.querySelector("#analysis-error"); const captureControls = document.querySelector("#capture-controls"); const resultsPanel = document.querySelector("#analysis-results");
  const retryButton = document.querySelector("#retry-analysis");
  const imageInput = document.querySelector("#analysis-image"); const preview = document.querySelector("#image-preview"); const processImageButton = document.querySelector("#process-image");
  const video = document.querySelector("#camera-video"); const cameraSelect = document.querySelector("#camera-select"); const startCameraButton = document.querySelector("#start-camera"); const finishVideoButton = document.querySelector("#finish-video"); const captureStatus = document.querySelector("#capture-status");
  let analysis = null; let stream = null; let streaming = false; let loopPromise = null;
  const csrf = () => document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("csrftoken="))?.split("=").slice(1).join("=");
  async function api(url, method = "GET", payload = null) {
    const response = await fetch(url, { method, credentials: "same-origin", headers: payload ? { "Content-Type": "application/json", "X-CSRFToken": csrf() || "" } : {}, body: payload ? JSON.stringify(payload) : undefined });
    const data = await response.json().catch(() => ({})); if (!response.ok) { const error = new Error(errorMessage(data) || `Solicitud fallida (${response.status}).`); error.data = data; throw error; } return data;
  }
  // DRF devuelve los errores como lista, {detail} o {campo: [mensajes]}.
  function errorMessage(data) {
    if (Array.isArray(data)) return data.join(" ");
    if (!data || typeof data !== "object") return "";
    if (data.error_message || data.detail) return data.error_message || data.detail;
    return Object.values(data).flat().filter((value) => typeof value === "string").join(" ");
  }
  const showError = (message) => { errorPanel.textContent = message; errorPanel.hidden = false; };
  const updateSource = () => { imageControls.hidden = source.value !== "imagen"; videoControls.hidden = source.value !== "video"; };
  async function sendFrame(imageBase64) {
    const result = await api(`/api/analyses/${analysis.id}/frames/`, "POST", { frame_id: crypto.randomUUID(), attempt: analysis.attempt, captured_at: new Date().toISOString(), image_base64: imageBase64 });
    captureStatus.textContent = `Fotogramas procesados. Conteo de paso: ${result.counters?.counted ?? 0}.`; return result;
  }
  async function finishAnalysis() {
    const completed = await api(`/api/analyses/${analysis.id}/complete/`, "POST", {});
    const detail = await api(`/api/history/${analysis.id}/`); captureControls.hidden = true; resultsPanel.hidden = false; form.hidden = true;
    window.SmartShrimpResults.render(document.querySelector("#results-summary"), detail);
  }
  async function stopCameraAndFinish() {
    streaming = false; if (loopPromise) await loopPromise; stream?.getTracks().forEach((track) => track.stop()); stream = null; video.srcObject = null;
    document.querySelector("#live-indicator").hidden = true; finishVideoButton.disabled = true; startCameraButton.disabled = true;
    try { await finishAnalysis(); } catch (error) { showError(error.message); }
  }
  async function streamFrames() {
    const intervalMs = 1000 / 15;
    while (streaming) { const startedAt = performance.now(); try { await sendFrame(await window.SmartShrimpCapture.videoAsBase64(video)); } catch (error) { streaming = false; showError(error.message); break; }
      const remaining = intervalMs - (performance.now() - startedAt); if (remaining > 0) await new Promise((resolve) => setTimeout(resolve, remaining)); }
  }
  source.addEventListener("change", updateSource);
  imageInput.addEventListener("change", () => { const file = imageInput.files?.[0]; processImageButton.disabled = !file; preview.hidden = !file; if (file) preview.src = URL.createObjectURL(file); });
  form.addEventListener("submit", async (event) => { event.preventDefault(); errorPanel.hidden = true; const data = new FormData(form);
    try { analysis = await api("/api/analyses/", "POST", { batch_code: data.get("batch_code"), source: data.get("source") }); if (analysis.status !== "en_curso") throw new Error(analysis.error_message || "No se pudo iniciar el análisis."); form.querySelector("button[type=submit]").disabled = true; captureControls.hidden = false; updateSource(); }
    catch (error) {
      showError(typeof error.message === "string" ? error.message : JSON.stringify(error.message));
      if (error.data?.id) { analysis = error.data; form.hidden = true; retryButton.hidden = false; }
    }
  });
  processImageButton.addEventListener("click", async () => { processImageButton.disabled = true; try { await sendFrame(await window.SmartShrimpCapture.fileAsBase64(imageInput.files[0])); await finishAnalysis(); } catch (error) { showError(error.message); processImageButton.disabled = false; } });
  startCameraButton.addEventListener("click", async () => { try {
    const deviceId = cameraSelect.value; stream = await navigator.mediaDevices.getUserMedia({ video: deviceId ? { deviceId: { exact: deviceId } } : true, audio: false }); video.srcObject = stream; await video.play();
    const devices = await navigator.mediaDevices.enumerateDevices(); cameraSelect.replaceChildren(...devices.filter((device) => device.kind === "videoinput").map((device, index) => { const option = document.createElement("option"); option.value = device.deviceId; option.textContent = device.label || `Cámara ${index + 1}`; return option; }));
    document.querySelector("#live-indicator").hidden = false; finishVideoButton.disabled = false; startCameraButton.disabled = true; streaming = true; loopPromise = streamFrames();
  } catch (error) { showError(`No se pudo iniciar la cámara: ${error.message}`); } });
  finishVideoButton.addEventListener("click", stopCameraAndFinish); updateSource();
  retryButton.addEventListener("click", async () => {
    retryButton.disabled = true;
    try {
      const retried = await api(`/api/analyses/${analysis.id}/`, "POST", {});
      analysis = retried; errorPanel.hidden = retried.status === "en_curso";
      if (retried.status !== "en_curso") { retryButton.disabled = false; showError(retried.error_message || "El reintento no pudo iniciar."); return; }
      stream?.getTracks().forEach((track) => track.stop()); stream = null; video.srcObject = null;
      startCameraButton.disabled = false; finishVideoButton.disabled = true; processImageButton.disabled = !imageInput.files?.length;
      retryButton.hidden = true; retryButton.disabled = false; captureControls.hidden = false; resultsPanel.hidden = true; form.hidden = true; updateSource();
      captureStatus.textContent = `Reintento ${analysis.attempt} en curso. Captura el lote de nuevo.`;
    } catch (error) {
      if (error.data?.id) analysis = error.data;
      showError(error.message); retryButton.disabled = false;
    }
  });
})();
