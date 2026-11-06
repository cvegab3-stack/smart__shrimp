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
  // Indicador de pasos: 1 Identificación → 2 Captura → 3 Resultados.
  function setStep(current) { document.querySelectorAll("#analysis-stepper .step").forEach((step, index) => { const number = index + 1;
    step.classList.toggle("done", number < current); step.classList.toggle("active", number === current);
    step.querySelector(".step-number").textContent = number < current ? "✓" : String(number);
    if (number === current) step.setAttribute("aria-current", "step"); else step.removeAttribute("aria-current"); }); }

  // Recuadros en vivo sobre la cámara, con el tamaño de cada camarón. bbox llega en píxeles del fotograma enviado;
  // el video se muestra con object-fit: contain, así que se escala y se centra igual que la imagen.
  const overlay = document.querySelector("#camera-overlay"); const SIZE_NAMES = { pequeno: "Pequeño", mediano: "Mediano", grande: "Grande" };
  const SIZE_COLORS = { pequeno: "#12b5c4", mediano: "#d69a17", grande: "#7c4dff" };
  function drawLive(detections) { if (!overlay || !video.videoWidth) return; const ratio = window.devicePixelRatio || 1;
    const width = overlay.clientWidth; const height = overlay.clientHeight; overlay.width = width * ratio; overlay.height = height * ratio;
    const context = overlay.getContext("2d"); context.setTransform(ratio, 0, 0, ratio, 0, 0); context.clearRect(0, 0, width, height);
    const scale = Math.min(width / video.videoWidth, height / video.videoHeight); const offsetX = (width - video.videoWidth * scale) / 2; const offsetY = (height - video.videoHeight * scale) / 2;
    (detections || []).forEach((item) => { const [x1, y1, x2, y2] = item.bbox; const color = SIZE_COLORS[item.size_category] || "#8b9aa8";
      const left = offsetX + x1 * scale; const top = offsetY + y1 * scale;
      context.lineWidth = 3; context.strokeStyle = color; context.strokeRect(left, top, (x2 - x1) * scale, (y2 - y1) * scale);
      const label = `${SIZE_NAMES[item.size_category] || (item.length_cm == null ? "Sin medida" : "Fuera de rango")}${item.length_cm == null ? "" : ` · ${item.length_cm.toFixed(1).replace(".", ",")} cm`}`;
      context.font = "bold 14px sans-serif"; const labelWidth = context.measureText(label).width + 12;
      context.fillStyle = color; context.fillRect(left, Math.max(0, top - 22), labelWidth, 22); context.fillStyle = "#fff"; context.fillText(label, left + 6, Math.max(15, top - 6)); }); }
  const clearLive = () => overlay?.getContext("2d").clearRect(0, 0, overlay.width, overlay.height);

  // Resolución en que se midió la calibración (herramienta 📏). Si la imagen o la cámara no coinciden, se avisa
  // ANTES de analizar: sus píxeles no equivalen a los mismos centímetros.
  const app = document.querySelector("#analysis-app");
  const calibrationSize = app.dataset.calibrationWidth ? [Number(app.dataset.calibrationWidth), Number(app.dataset.calibrationHeight)] : null;
  function warnResolution(width, height, container) { container.querySelector(".resolution-warning")?.remove();
    if (!calibrationSize || !width || (width === calibrationSize[0] && height === calibrationSize[1])) return;
    const warning = document.createElement("div"); warning.className = "alert alert-amber resolution-warning"; warning.setAttribute("role", "status");
    warning.textContent = `Esta ${container === videoControls ? "cámara entrega" : "imagen mide"} ${width} × ${height} px, pero la calibración se midió en ${calibrationSize[0]} × ${calibrationSize[1]} px: las longitudes y los tamaños no serán fiables. Usa la misma cámara y resolución que en la calibración.`;
    container.prepend(warning); }
  const updateSource = () => { imageControls.hidden = source.value !== "imagen"; videoControls.hidden = source.value !== "video"; };
  // Fotogramas por segundo realmente procesados (media de los últimos 2 s): permite comprobar la velocidad.
  let frameTimes = [];
  async function sendFrame(imageBase64) {
    const result = await api(`/api/analyses/${analysis.id}/frames/`, "POST", { frame_id: crypto.randomUUID(), attempt: analysis.attempt, captured_at: new Date().toISOString(), image_base64: imageBase64 });
    const now = performance.now(); frameTimes = [...frameTimes.filter((time) => now - time < 2000), now];
    if (streaming) { drawLive(result.detections);
      captureStatus.textContent = `En pantalla: ${result.detections?.length ?? 0} · Contados al cruzar la línea: ${result.counters?.counted ?? 0} · ${Math.round(frameTimes.length / 2)} fotogramas/s`; }
    return result;
  }
  async function finishAnalysis(elapsedSince) {
    await api(`/api/analyses/${analysis.id}/complete/`, "POST", {});
    const detail = await api(`/api/history/${analysis.id}/`); captureControls.hidden = true; resultsPanel.hidden = false; form.hidden = true; setStep(3);
    window.SmartShrimpResults.render(document.querySelector("#results-summary"), detail, elapsedSince === undefined ? {} : { elapsedMs: performance.now() - elapsedSince });
  }
  async function stopCameraAndFinish() {
    streaming = false; if (loopPromise) await loopPromise; clearLive(); stream?.getTracks().forEach((track) => track.stop()); stream = null; video.srcObject = null;
    document.querySelector("#live-indicator").hidden = true; finishVideoButton.disabled = true; startCameraButton.disabled = true;
    try { await finishAnalysis(); } catch (error) { showError(error.message); }
  }
  async function streamFrames() {
    const intervalMs = 1000 / 15;
    while (streaming) { const startedAt = performance.now(); try { await sendFrame(await window.SmartShrimpCapture.videoAsBase64(video)); } catch (error) { streaming = false; showError(error.message); break; }
      const remaining = intervalMs - (performance.now() - startedAt); if (remaining > 0) await new Promise((resolve) => setTimeout(resolve, remaining)); }
  }
  source.addEventListener("change", updateSource);
  imageInput.addEventListener("change", async () => { const file = imageInput.files?.[0]; processImageButton.disabled = !file; preview.hidden = !file; warnResolution(0, 0, imageControls);
    if (!file) return; preview.src = URL.createObjectURL(file);
    try { const bitmap = await createImageBitmap(file); warnResolution(bitmap.width, bitmap.height, imageControls); bitmap.close?.(); } catch { /* la imagen no se pudo leer: lo dirá el análisis */ } });
  form.addEventListener("submit", async (event) => { event.preventDefault(); errorPanel.hidden = true; const data = new FormData(form);
    try { analysis = await api("/api/analyses/", "POST", { batch_code: data.get("batch_code"), source: data.get("source") }); if (analysis.status !== "en_curso") throw new Error(analysis.error_message || "No se pudo iniciar el análisis."); form.querySelector("button[type=submit]").disabled = true; captureControls.hidden = false; updateSource(); setStep(2); }
    catch (error) {
      showError(typeof error.message === "string" ? error.message : JSON.stringify(error.message));
      if (error.data?.id) { analysis = error.data; form.hidden = true; retryButton.hidden = false; }
    }
  });
  processImageButton.addEventListener("click", async () => { processImageButton.disabled = true; const startedAt = performance.now(); captureStatus.textContent = "Analizando la imagen…";
    try { await sendFrame(await window.SmartShrimpCapture.fileAsBase64(imageInput.files[0])); await finishAnalysis(startedAt); } catch (error) { showError(error.message); processImageButton.disabled = false; } });
  startCameraButton.addEventListener("click", async () => { try {
    // Se pide a la cámara la resolución en que se midió la calibración, para que sus píxeles equivalgan a los mismos cm.
    const deviceId = cameraSelect.value; const constraints = {};
    if (deviceId) constraints.deviceId = { exact: deviceId };
    if (calibrationSize) { constraints.width = { ideal: calibrationSize[0] }; constraints.height = { ideal: calibrationSize[1] }; }
    stream = await navigator.mediaDevices.getUserMedia({ video: Object.keys(constraints).length ? constraints : true, audio: false }); video.srcObject = stream; await video.play();
    warnResolution(video.videoWidth, video.videoHeight, videoControls);
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
      captureStatus.textContent = `Reintento ${analysis.attempt} en curso. Captura el lote de nuevo.`; setStep(2);
    } catch (error) {
      if (error.data?.id) analysis = error.data;
      showError(error.message); retryButton.disabled = false;
    }
  });
})();
