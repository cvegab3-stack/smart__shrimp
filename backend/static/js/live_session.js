"use strict";
// Flujo de análisis del operador: 1 Identificación → 2 Captura → 3 Resultados.
// El tipo se elige antes, en «Nuevo análisis»; cada tipo tiene su página (data-source del <main>):
//   - Foto de un camarón (imagen): sin datos de lote.
//   - Conteo de lote con cámara (video): pide los datos del lote y, al aceptarlos, abre la cámara y empieza a contar.
//
// La pantalla es una máquina de estados que siempre refleja el estado real del análisis en el servidor:
//   foto:   capturar (el análisis se crea al pulsar «Analizar imagen») → resultados
//   cámara: identificar → (crear) → capturar → (finalizar) → resultados
//                    capturar → (falla del servicio) → error → (reintentar) → capturar
// Errores (ver apps/analysis/errors.py):
//   - entrada (422): culpa del archivo. El análisis sigue en curso: se elige otra imagen.
//   - transitorio / configuración (503, 409 con el análisis): el análisis quedó con error → «Reintentar».
//   - sin conexión (status 0): no se sabe si llegó; se mantiene la pantalla y se puede volver a pulsar.
(() => {
  const app = document.querySelector("#analysis-app");
  const form = document.querySelector("#analysis-create-form"); if (!app || !form) return;
  const $ = (selector) => document.querySelector(selector);
  const batchInput = $("#batch-code"); const createButton = $("#create-analysis");
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
  const lotStrip = $("#lot-strip"); const liveCount = $("#live-count"); const liveExpected = $("#live-expected");
  const backLink = $("#back-link"); const lotDate = $("#lot-date");
  window.SmartShrimp.watchCameraSelect(cameraSelect);  // recuerda la cámara elegida (también la usa la calibración)

  let analysis = null;        // estado del análisis tal como lo devolvió el servidor
  let mode = "identify";      // identify | capture | error | results
  const chosenSource = app.dataset.source === "video" ? "video" : "imagen";  // tipo de esta página
  let cameraListReady = null; // lista de cámaras cargándose: la cámara se abre sola cuando termina
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
  const currentSource = () => analysis?.source ?? chosenSource;
  const lot = () => currentSource() === "imagen" ? "Foto de un camarón" : analysis ? `Lote ${analysis.batch_code}` : "";

  // Cada modo decide qué se ve y qué acciones son válidas: nunca queda un botón que el servidor vaya a rechazar.
  function setMode(next, message = "") {
    mode = next;
    form.hidden = next !== "identify";
    captureControls.hidden = next !== "capture";
    resultsPanel.hidden = next !== "results";
    retryActions.hidden = next !== "error";
    showError(next === "error" || next === "identify" ? message : "");
    backLink.hidden = next === "capture" && Boolean(analysis);  // con un análisis en marcha no se cambia de tipo
    if (next === "identify") { setStep(1); flowTitle.textContent = "Datos del lote"; flowSubtitle.textContent = "Rellena los datos y pulsa «Iniciar conteo»: la cámara se abrirá y empezará a contar."; }
    if (next === "capture") { setStep(2); flowTitle.textContent = currentSource() === "imagen" ? lot() : `${lot()} · conteo`;
      flowSubtitle.textContent = analysis?.attempt > 1 ? `Intento ${analysis.attempt}. Los intentos anteriores no se mezclan con este.`
        : currentSource() === "imagen" ? "Sube la foto de un camarón con la misma cámara de la calibración." : "Pasa los camarones por la línea de conteo con la misma cámara de la calibración.";
      if (analysis) calibrationSummary.textContent = `Versión ${analysis.calibration_version} (congelada para este análisis)`;
      imageControls.hidden = currentSource() !== "imagen"; videoControls.hidden = currentSource() !== "video";
      // Lista de cámaras ANTES de iniciar: así se elige la correcta (p. ej. Camo) sin empezar a analizar con otra.
      if (currentSource() === "video" && !stream) cameraListReady = window.SmartShrimp.fillCameraSelect(cameraSelect, { askPermission: true }); }
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

  // ---------- Paso 1: elegir el tipo y, en cámara, los datos del lote ----------
  const pad = (value) => String(value).padStart(2, "0");
  const today = () => { const now = new Date(); return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`; };
  // Punto de partida de la página: foto → elegir la imagen; cámara → formulario del lote con código y fecha propuestos.
  function startFresh() {
    if (chosenSource === "imagen") { enterCapture(); return; }
    const now = new Date();  // código propuesto, p. ej. L-20261124-0930 (el operador puede cambiarlo)
    form.reset();
    batchInput.value = `L-${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}`;
    lotDate.value = today();
    setMode("identify"); batchInput.focus(); batchInput.select();
  }

  const LOT_LABELS = { batch_code: "Código del lote", lot_date: "Fecha de registro", lot_weight_kg: "Peso del lote",
    supplier: "Proveedor", pond: "Piscina", harvest_date: "Fecha de cosecha", product_presentation: "Presentación",
    declared_size: "Talla declarada", expected_count: "Cantidad esperada", product_temperature_c: "Temperatura", notes: "Observaciones" };
  const NUMBER_FIELDS = ["lot_weight_kg", "expected_count", "product_temperature_c"];
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); if (createButton.disabled) return;
    const body = { source: "video" };
    new FormData(form).forEach((value, name) => { const text = String(value).trim();
      if (name === "csrfmiddlewaretoken" || !text) return;
      body[name] = NUMBER_FIELDS.includes(name) ? Number(text.replace(",", ".")) : text; });
    const missing = [["batch_code", batchInput, "Escribe el código o nombre del lote."], ["lot_date", lotDate, "Indica la fecha de registro del lote."],
      ["lot_weight_kg", $("#lot-weight"), "Indica el peso del lote en kg."]].find(([name]) => body[name] === undefined);
    if (missing) { showError(missing[2]); missing[1].focus(); return; }
    if (!(body.lot_weight_kg > 0)) { showError("El peso del lote debe ser un número mayor que 0."); $("#lot-weight").focus(); return; }
    setBusy(createButton, true, "Iniciando…"); showError("");
    try {
      analysis = await window.SmartShrimp.request("/api/analyses/", { method: "POST", body, labels: LOT_LABELS });
      enterCapture();
      // La cámara se abre sola en cuanto está lista la lista de cámaras (así usa la cámara elegida, p. ej. Camo).
      Promise.resolve(cameraListReady).catch(() => {}).then(() => {
        if (mode === "capture" && analysis?.source === "video" && !stream && !startCameraButton.disabled) startCameraButton.click(); });
    }
    catch (error) { if (error.data?.id) handleFailure(error); else showError(error.message); }
    finally { setBusy(createButton, false); createButton.disabled = false; }
  });

  function enterCapture({ retried = false } = {}) {
    framesOk = 0; setMode("capture"); finishVideoButton.disabled = true; startCameraButton.disabled = false;
    showImageProblem(""); liveCount.textContent = "0";
    liveExpected.textContent = analysis?.expected_count ? ` de ${analysis.expected_count} esperados` : "";
    lotStrip.replaceChildren(); lotStrip.hidden = !analysis || analysis.source !== "video";
    if (analysis?.source === "video") { const { el } = window.SmartShrimp;
      lotStrip.append(el("strong", "", `Lote ${analysis.batch_code}`));
      (analysis.lot || []).filter((row) => ["Fecha de registro", "Peso del lote"].includes(row.label))
        .forEach((row) => lotStrip.append(el("span", "", `${row.label}: ${row.value}`))); }
    if (currentSource() === "imagen") {
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

  const dropzone = $("#image-dropzone"); const dropzoneFile = $("#dropzone-file"); let dropNote = "";
  // Con una imagen elegida, el recuadro grande se reduce a una barra: nombre de la foto y «Cambiar imagen»
  // (sigue aceptando que se suelte otra foto encima). Sin imagen, vuelve a ser el recuadro para arrastrar o elegir.
  const imageHelp = $("#analysis-image-help");
  const showChosen = (name) => {
    dropzoneFile.replaceChildren();
    if (name) { const { el } = window.SmartShrimp;
      dropzoneFile.append(el("span", "dropzone-file-name", `Imagen elegida: ${name}`), el("span", "dropzone-link", "Cambiar imagen")); }
    dropzoneFile.hidden = !name; imageHelp.hidden = Boolean(name); dropzone.classList.toggle("has-file", Boolean(name));
  };
  imageInput.addEventListener("change", async () => {
    const file = imageInput.files?.[0]; selectedFile = null; processImageButton.disabled = true; preview.hidden = true; showImageProblem(""); warnResolution(0, 0, imageControls); showChosen("");
    if (!file) return;
    const check = await window.SmartShrimp.validateImageFile(file, { minSide: MIN_IMAGE_SIDE });
    if (!check.ok) { showImageProblem(check.message); imageInput.value = ""; dropNote = ""; return; }
    showChosen(file.name);
    warnResolution(check.bitmap.width, check.bitmap.height, imageControls); check.bitmap.close?.();
    if (preview.src.startsWith("blob:")) URL.revokeObjectURL(preview.src);
    selectedFile = file; preview.src = URL.createObjectURL(file); preview.hidden = false; processImageButton.disabled = false;
    captureStatus.textContent = `Imagen lista. Pulsa «Analizar imagen».${dropNote ? ` ${dropNote}` : ""}`; dropNote = "";
  });

  // Arrastrar y soltar: la foto soltada se entrega al mismo <input type="file">, así pasa por la misma validación
  // que al elegirla con clic. Mientras se analiza (campo deshabilitado) no se aceptan fotos.
  const draggingFiles = (event) => [...(event.dataTransfer?.types || [])].includes("Files");
  let dragDepth = 0;
  dropzone.addEventListener("dragenter", (event) => { if (!draggingFiles(event)) return; event.preventDefault(); dragDepth += 1; dropzone.classList.toggle("is-dragover", !imageInput.disabled); });
  dropzone.addEventListener("dragover", (event) => { if (!draggingFiles(event)) return; event.preventDefault(); event.dataTransfer.dropEffect = imageInput.disabled ? "none" : "copy"; });
  dropzone.addEventListener("dragleave", () => { dragDepth = Math.max(0, dragDepth - 1); if (!dragDepth) dropzone.classList.remove("is-dragover"); });
  dropzone.addEventListener("drop", (event) => {
    if (!draggingFiles(event)) return; event.preventDefault(); dragDepth = 0; dropzone.classList.remove("is-dragover");
    if (imageInput.disabled) return;
    const files = [...event.dataTransfer.files];
    if (!files.length) return;
    // El aviso se muestra junto con «Imagen lista» cuando termina la validación (que es asíncrona).
    dropNote = files.length > 1 ? `Soltaste ${files.length} fotos: se usa solo la primera (un análisis por imagen).` : "";
    const transfer = new DataTransfer(); transfer.items.add(files[0]); imageInput.files = transfer.files;
    imageInput.dispatchEvent(new Event("change"));
  });
  // Una foto soltada fuera del recuadro no debe abrirse en el navegador (se perdería la página del análisis).
  ["dragover", "drop"].forEach((type) => window.addEventListener(type, (event) => { if (draggingFiles(event) && !dropzone.contains(event.target)) event.preventDefault(); }));

  let analyzing = false;
  async function analyzeImage() {
    if (analyzing || !selectedFile) return; analyzing = true; backLink.hidden = true;
    const startedAt = performance.now(); setBusy(processImageButton, true, "Analizando…"); imageInput.disabled = true; showImageProblem("");
    captureStatus.textContent = "Analizando la imagen… puede tardar unos segundos.";
    try {
      const imageBase64 = await window.SmartShrimpCapture.fileAsBase64(selectedFile);
      const bytes = window.SmartShrimpCapture.base64Bytes(imageBase64);
      if (bytes > MAX_IMAGE_BYTES) { const mb = (value) => (value / 1048576).toFixed(1).replace(".", ",");
        showImageProblem(`La imagen pesa ${mb(bytes)} MB ya convertida y el máximo es ${mb(MAX_IMAGE_BYTES)} MB. Usa una foto más liviana.`); return; }
      if (!analysis) {  // foto suelta: el análisis se crea ahora, no al elegir la tarjeta (así no queda a medias)
        analysis = await api("/api/analyses/", "POST", { source: "imagen" });
        calibrationSummary.textContent = `Versión ${analysis.calibration_version} (congelada para este análisis)`; }
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
    if (streaming) { drawLive(result.detections); liveCount.textContent = String(result.counters?.counted ?? 0);
      captureStatus.textContent = `En pantalla: ${result.detections?.length ?? 0} · Contados al cruzar la línea: ${result.counters?.counted ?? 0} · ${Math.round(frameTimes.length / 2)} fotogramas/s`; }
    return result;
  }

  // Apaga la cámara y deja los botones según el estado: solo se puede volver a iniciar si el análisis sigue en curso.
  function stopCamera() {
    streaming = false; clearLive(); stream?.getTracks().forEach((track) => track.stop()); stream = null; video.srcObject = null;
    cameraSelect.disabled = false;
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
      const constraints = window.SmartShrimp.cameraConstraint(cameraSelect);
      if (calibrationSize) { constraints.width = { ideal: calibrationSize[0] }; constraints.height = { ideal: calibrationSize[1] }; }
      stream = await navigator.mediaDevices.getUserMedia({ video: Object.keys(constraints).length ? constraints : true, audio: false }); video.srcObject = stream; await video.play();
      warnResolution(video.videoWidth, video.videoHeight, videoControls);
      // Muestra qué cámara quedó abierta (si era la predeterminada, su nombre real) y no deja cambiarla a mitad del
      // análisis: los fotogramas de otra cámara romperían el seguimiento y la escala de la calibración.
      await window.SmartShrimp.fillCameraSelect(cameraSelect);
      const opened = stream.getVideoTracks()[0]?.getSettings?.().deviceId;
      if (opened && [...cameraSelect.options].some((o) => o.value === opened)) cameraSelect.value = opened;
      cameraSelect.disabled = true;
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
    showImageProblem(""); showChosen(""); warnResolution(0, 0, imageControls); warnResolution(0, 0, videoControls);
    startFresh();
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
  else startFresh();
})();
