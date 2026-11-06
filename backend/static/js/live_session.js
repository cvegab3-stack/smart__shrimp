"use strict";
// Flujo de análisis del operador: 1 Identificación → 2 Captura → 3 Resultados.
//
// La pantalla es una máquina de estados que siempre refleja el estado real del análisis en el servidor:
//   identificar → (crear) → capturar → (finalizar) → resultados
//                    capturar → (falla del servicio) → error → (reintentar) → capturar
// Errores (ver apps/analysis/errors.py):
//   - entrada (422): culpa del archivo. El análisis sigue en curso: se elige otra imagen.
//   - transitorio / configuración (503, 409 con el análisis): el análisis quedó con error → «Reintentar».
//   - sin conexión (status 0): no se sabe si llegó; se mantiene la pantalla y se puede volver a pulsar.
(() => {
  const app = document.querySelector("#analysis-app");
  const form = document.querySelector("#analysis-create-form"); if (!app || !form) return;
  const $ = (selector) => document.querySelector(selector);
  const source = $("#source-type"); const batchInput = $("#batch-code"); const createButton = $("#create-analysis");
  const flowTitle = $("#flow-title"); const flowSubtitle = $("#flow-subtitle");
  const errorPanel = $("#analysis-error"); const retryActions = $("#retry-actions"); const retryButton = $("#retry-analysis");
  const discardButton = $("#discard-analysis"); const captureControls = $("#capture-controls"); const resultsPanel = $("#analysis-results");
  const imageControls = $("#image-controls"); const videoControls = $("#video-controls"); const captureStatus = $("#capture-status");
  const imageInput = $("#analysis-image"); const imageProblem = $("#image-problem"); const preview = $("#image-preview");
  const processImageButton = $("#process-image"); const calibrationSummary = $("#calibration-summary");
  const video = $("#camera-video"); const cameraSelect = $("#camera-select"); const startCameraButton = $("#start-camera");
  const finishVideoButton = $("#finish-video"); const liveIndicator = $("#live-indicator"); const newAnalysisButton = $("#new-analysis");
  const api = (url, method = "GET", body) => window.SmartShrimp.request(url, { method, body });
  const MAX_IMAGE_BYTES = Number(app.dataset.maxImageBytes) || 12 * 1024 * 1024;
  const MIN_IMAGE_SIDE = Number(app.dataset.minImageSide) || 0;
  const SOURCE_KEY = "smartShrimp.lastSource";

  let analysis = null;        // estado del análisis tal como lo devolvió el servidor
  let mode = "identify";      // identify | capture | error | results
  let selectedFile = null;    // imagen validada (se reutiliza sola al reintentar)
  let stream = null; let streaming = false; let loopPromise = null; let framesOk = 0;

  // ---------- Presentación ----------
  function setStep(current, failed = false) {
    document.querySelectorAll("#analysis-stepper .step").forEach((step, index) => { const number = index + 1;
      step.classList.toggle("done", number < current); step.classList.toggle("active", number === current);
      step.classList.toggle("failed", failed && number === current);
      step.querySelector(".step-number").textContent = number < current ? "✓" : failed && number === current ? "!" : String(number);
      if (number === current) step.setAttribute("aria-current", "step"); else step.removeAttribute("aria-current"); });
  }
  function showError(message) { errorPanel.textContent = message; errorPanel.hidden = !message; }
  function showImageProblem(message) { imageProblem.textContent = message || ""; imageProblem.hidden = !message; }
  function setBusy(button, busy, busyText) {
    if (!button) return;
    if (busy) { button.dataset.label ??= button.textContent; button.textContent = busyText; button.disabled = true; button.setAttribute("aria-busy", "true"); }
    else { if (button.dataset.label) button.textContent = button.dataset.label; button.removeAttribute("aria-busy"); }
  }
  const lot = () => analysis ? `Lote ${analysis.batch_code}` : "";

  // Cada modo decide qué se ve y qué acciones son válidas: nunca queda un botón que el servidor vaya a rechazar.
  function setMode(next, message = "") {
    mode = next;
    form.hidden = next !== "identify";
    captureControls.hidden = next !== "capture";
    resultsPanel.hidden = next !== "results";
    retryActions.hidden = next !== "error";
    showError(next === "error" || next === "identify" ? message : "");
    if (next === "identify") { setStep(1); flowTitle.textContent = "Identifica el lote"; flowSubtitle.textContent = "El análisis conservará la calibración vigente al iniciarse."; }
    if (next === "capture") { setStep(2); flowTitle.textContent = `${lot()} · captura`;
      flowSubtitle.textContent = analysis.attempt > 1 ? `Intento ${analysis.attempt}. Los intentos anteriores no se mezclan con este.` : "Captura el lote con la misma cámara de la calibración.";
      calibrationSummary.textContent = `Versión ${analysis.calibration_version} (congelada para este lote)`;
      imageControls.hidden = analysis.source !== "imagen"; videoControls.hidden = analysis.source !== "video"; }
    if (next === "error") { setStep(2, true); flowTitle.textContent = `${lot()} · no se pudo completar`;
      flowSubtitle.textContent = "El lote quedó guardado con el error; reintentarlo abre un intento nuevo."; retryButton.disabled = false; discardButton.disabled = false; retryButton.focus(); }
    if (next === "results") { setStep(3); flowTitle.textContent = `${lot()} · resultados`; flowSubtitle.textContent = "Resultados guardados en el historial."; newAnalysisButton.focus(); }
  }

  // ---------- Errores ----------
  // Decide la reacción según la respuesta del servidor (ver la cabecera del archivo).
  function handleFailure(error, { inputTarget = "panel" } = {}) {
    if (error.status === 401) return;  // session_timeout.js lleva al acceso
    const data = error.data || {};
    if (data.error_kind === "entrada") {  // el análisis sigue en curso: corregir y reenviar
      if (inputTarget === "image") showImageProblem(error.message); else captureStatus.textContent = error.message;
      return;
    }
    if (data.id) {
      analysis = data;
      if (data.status === "con_error") { setMode("error", error.message); return; }
      if (data.status === "finalizado") { loadFinished(); return; }
      if (data.status === "en_curso") { if (mode !== "capture") enterCapture(); captureStatus.textContent = error.message; return; }
    }
    // Sin conexión u otro fallo sin estado: se mantiene la pantalla y se informa.
    if (mode === "capture") captureStatus.textContent = error.message; else showError(error.message);
  }
  async function loadFinished() {
    try { const detail = await api(`/api/history/${analysis.id}/`); showResults(detail); }
    catch (error) { showError(error.message); }
  }

  // ---------- Paso 1: identificación ----------
  try { const saved = localStorage.getItem(SOURCE_KEY); if (saved && [...source.options].some((o) => o.value === saved)) source.value = saved; } catch { /* sin almacenamiento */ }
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); if (createButton.disabled) return;
    const data = new FormData(form); const batchCode = String(data.get("batch_code") || "").trim();
    if (!batchCode) { showError("Escribe el código del lote."); batchInput.focus(); return; }
    try { localStorage.setItem(SOURCE_KEY, source.value); } catch { /* sin almacenamiento */ }
    setBusy(createButton, true, "Creando…"); showError("");
    try { analysis = await api("/api/analyses/", "POST", { batch_code: batchCode, source: source.value }); enterCapture(); }
    catch (error) { if (error.data?.id) handleFailure(error); else showError(error.message); }
    finally { setBusy(createButton, false); createButton.disabled = false; }
  });

  function enterCapture({ retried = false } = {}) {
    framesOk = 0; setMode("capture"); finishVideoButton.disabled = true; startCameraButton.disabled = false;
    showImageProblem("");
    if (analysis.source === "imagen") {
      processImageButton.disabled = !selectedFile; imageInput.disabled = false;
      if (retried && selectedFile) { captureStatus.textContent = `Intento ${analysis.attempt}: analizando la misma imagen…`; analyzeImage(); }
      else captureStatus.textContent = retried ? `Intento ${analysis.attempt}: elige la imagen del lote.` : "Elige la imagen del lote y pulsa «Analizar imagen».";
    } else captureStatus.textContent = retried ? `Intento ${analysis.attempt}: inicia la cámara y captura el lote de nuevo.` : "Inicia la cámara; cuando se analice el primer fotograma podrás finalizar.";
  }

  // ---------- Paso 2: imagen ----------
  const calibrationSize = app.dataset.calibrationWidth ? [Number(app.dataset.calibrationWidth), Number(app.dataset.calibrationHeight)] : null;
  function warnResolution(width, height, container) { container.querySelector(".resolution-warning")?.remove();
    if (!calibrationSize || !width || (width === calibrationSize[0] && height === calibrationSize[1])) return;
    const warning = document.createElement("div"); warning.className = "alert alert-amber resolution-warning"; warning.setAttribute("role", "status");
    warning.textContent = `Esta ${container === videoControls ? "cámara entrega" : "imagen mide"} ${width} × ${height} px, pero la calibración se midió en ${calibrationSize[0]} × ${calibrationSize[1]} px: las longitudes y los tamaños no serán fiables. Usa la misma cámara y resolución que en la calibración.`;
    container.prepend(warning); }

  imageInput.addEventListener("change", async () => {
    const file = imageInput.files?.[0]; selectedFile = null; processImageButton.disabled = true; preview.hidden = true; showImageProblem(""); warnResolution(0, 0, imageControls);
    if (!file) return;
    const check = await window.SmartShrimp.validateImageFile(file, { minSide: MIN_IMAGE_SIDE });
    if (!check.ok) { showImageProblem(check.message); imageInput.value = ""; return; }
    warnResolution(check.bitmap.width, check.bitmap.height, imageControls); check.bitmap.close?.();
    if (preview.src.startsWith("blob:")) URL.revokeObjectURL(preview.src);
    selectedFile = file; preview.src = URL.createObjectURL(file); preview.hidden = false; processImageButton.disabled = false;
    captureStatus.textContent = "Imagen lista. Pulsa «Analizar imagen».";
  });

  let analyzing = false;
  async function analyzeImage() {
    if (analyzing || !selectedFile) return; analyzing = true;
    const startedAt = performance.now(); setBusy(processImageButton, true, "Analizando…"); imageInput.disabled = true; showImageProblem("");
    captureStatus.textContent = "Analizando la imagen… puede tardar unos segundos.";
    try {
      const imageBase64 = await window.SmartShrimpCapture.fileAsBase64(selectedFile);
      const bytes = window.SmartShrimpCapture.base64Bytes(imageBase64);
      if (bytes > MAX_IMAGE_BYTES) { const mb = (value) => (value / 1048576).toFixed(1).replace(".", ",");
        showImageProblem(`La imagen pesa ${mb(bytes)} MB ya convertida y el máximo es ${mb(MAX_IMAGE_BYTES)} MB. Usa una foto más liviana.`); return; }
      await sendFrame(imageBase64); framesOk += 1;
      await finishAnalysis(startedAt);
    } catch (error) { handleFailure(error, { inputTarget: "image" }); }
    finally { analyzing = false; setBusy(processImageButton, false); imageInput.disabled = false; processImageButton.disabled = !selectedFile || mode !== "capture"; }
  }
  processImageButton.addEventListener("click", analyzeImage);

  // ---------- Paso 2: video ----------
  const overlay = $("#camera-overlay"); const SIZE_NAMES = { pequeno: "Pequeño", mediano: "Mediano", grande: "Grande" };
  const SIZE_COLORS = { pequeno: "#12b5c4", mediano: "#d69a17", grande: "#7c4dff" };
  // Recuadros en vivo: bbox llega en píxeles del fotograma; el video se muestra con object-fit: contain.
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

  let frameTimes = [];
  async function sendFrame(imageBase64) {
    const result = await api(`/api/analyses/${analysis.id}/frames/`, "POST", { frame_id: crypto.randomUUID(), attempt: analysis.attempt, captured_at: new Date().toISOString(), image_base64: imageBase64 });
    const now = performance.now(); frameTimes = [...frameTimes.filter((time) => now - time < 2000), now];
    if (streaming) { drawLive(result.detections);
      captureStatus.textContent = `En pantalla: ${result.detections?.length ?? 0} · Contados al cruzar la línea: ${result.counters?.counted ?? 0} · ${Math.round(frameTimes.length / 2)} fotogramas/s`; }
    return result;
  }

  // Apaga la cámara y deja los botones según el estado: solo se puede volver a iniciar si el análisis sigue en curso.
  function stopCamera() {
    streaming = false; clearLive(); stream?.getTracks().forEach((track) => track.stop()); stream = null; video.srcObject = null;
    liveIndicator.hidden = true; startCameraButton.disabled = mode !== "capture"; finishVideoButton.disabled = true;
  }
  async function streamFrames() {
    const intervalMs = 1000 / 15;
    while (streaming) { const startedAt = performance.now();
      try { await sendFrame(await window.SmartShrimpCapture.videoAsBase64(video)); framesOk += 1; if (streaming) finishVideoButton.disabled = false; }
      catch (error) { stopCamera(); handleFailure(error); break; }
      const remaining = intervalMs - (performance.now() - startedAt); if (remaining > 0) await new Promise((resolve) => setTimeout(resolve, remaining)); }
  }
  startCameraButton.addEventListener("click", async () => {
    if (!navigator.mediaDevices?.getUserMedia) { captureStatus.textContent = window.SmartShrimp.cameraErrorText({ name: "SecurityError" }); return; }
    setBusy(startCameraButton, true, "Abriendo cámara…");
    try {
      // Se pide la resolución en que se midió la calibración, para que sus píxeles equivalgan a los mismos cm.
      const deviceId = cameraSelect.value; const constraints = {};
      if (deviceId) constraints.deviceId = { exact: deviceId };
      if (calibrationSize) { constraints.width = { ideal: calibrationSize[0] }; constraints.height = { ideal: calibrationSize[1] }; }
      stream = await navigator.mediaDevices.getUserMedia({ video: Object.keys(constraints).length ? constraints : true, audio: false }); video.srcObject = stream; await video.play();
      warnResolution(video.videoWidth, video.videoHeight, videoControls);
      const devices = await navigator.mediaDevices.enumerateDevices(); const current = cameraSelect.value;
      cameraSelect.replaceChildren(...devices.filter((device) => device.kind === "videoinput").map((device, index) => new Option(device.label || `Cámara ${index + 1}`, device.deviceId)));
      if (current) cameraSelect.value = current;
      liveIndicator.hidden = false; setBusy(startCameraButton, false); startCameraButton.disabled = true; streaming = true;
      captureStatus.textContent = "Analizando… «Detener y finalizar» se habilita con el primer fotograma analizado.";
      loopPromise = streamFrames();
    } catch (error) { stopCamera(); setBusy(startCameraButton, false); startCameraButton.disabled = false; captureStatus.textContent = window.SmartShrimp.cameraErrorText(error); }
  });
  finishVideoButton.addEventListener("click", async () => {
    finishVideoButton.disabled = true; streaming = false; if (loopPromise) await loopPromise; stopCamera(); startCameraButton.disabled = true;
    if (mode !== "capture") return;  // el último fotograma falló y ya se mostró el error
    try { await finishAnalysis(); } catch (error) { handleFailure(error); if (mode === "capture") startCameraButton.disabled = false; }
  });

  // ---------- Paso 3: resultados ----------
  async function finishAnalysis(startedAt) {
    captureStatus.textContent = "Guardando resultados…";
    const detail = await api(`/api/analyses/${analysis.id}/complete/`, "POST", {});
    analysis = detail; showResults(detail, startedAt);
  }
  function showResults(detail, startedAt) {
    setMode("results");
    window.SmartShrimpResults.render($("#results-summary"), detail, startedAt === undefined ? {} : { elapsedMs: performance.now() - startedAt });
  }
  function resetToIdentify() {
    stopCamera(); analysis = null; selectedFile = null; framesOk = 0; imageInput.value = ""; preview.hidden = true; preview.removeAttribute("src");
    showImageProblem(""); warnResolution(0, 0, imageControls); warnResolution(0, 0, videoControls); batchInput.value = "";
    setMode("identify"); batchInput.focus();
  }
  newAnalysisButton.addEventListener("click", resetToIdentify);
  discardButton.addEventListener("click", resetToIdentify);  // el lote con error queda en «Mis lotes» para reintentarlo luego

  // ---------- Reintento ----------
  retryButton.addEventListener("click", async () => {
    setBusy(retryButton, true, "Reintentando…"); discardButton.disabled = true;
    try { analysis = await api(`/api/analyses/${analysis.id}/`, "POST", {}); enterCapture({ retried: true }); }
    catch (error) { handleFailure(error); }
    finally { setBusy(retryButton, false); retryButton.disabled = false; discardButton.disabled = false; }
  });

  // Salir con un análisis a medias: el navegador pide confirmación (si sale igual, el lote quedará «interrumpido»).
  window.addEventListener("beforeunload", (event) => { if (mode === "capture" && analysis?.status === "en_curso") { event.preventDefault(); event.returnValue = ""; } });
  window.addEventListener("pagehide", () => stream?.getTracks().forEach((track) => track.stop()));

  // Llegada desde «Mis lotes» con un lote con error: se abre directamente en el reintento.
  const retryData = document.getElementById("retry-analysis-data");
  if (retryData) { analysis = JSON.parse(retryData.textContent); setMode("error", analysis.operator_message || "Este lote no se pudo completar."); }
  else setMode("identify");
})();
