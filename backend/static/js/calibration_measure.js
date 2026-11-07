"use strict";
// Mide la "Medida equivalente (px)" con dos clics sobre una foto de la regla, en vez de calcularla a mano.
// La foto se toma con la cámara usando la MISMA configuración que el análisis en vivo (live_session.js:
// getUserMedia con la cámara elegida y su resolución por defecto) o se sube de esa cámara. Los clics se
// convierten a píxeles de la imagen original, que son los que recibe el detector.
(() => {
  const openButton = document.querySelector("#measure-open"); const panel = document.querySelector("#measure-panel");
  if (!openButton || !panel) return;
  const $ = (id) => document.querySelector(id);
  const video = $("#measure-video"); const canvas = $("#measure-canvas"); const status = $("#measure-status");
  const cameraSelect = $("#measure-camera"); const captureButton = $("#measure-capture"); const resetButton = $("#measure-reset");
  const applyButton = $("#measure-apply"); const pixelsInput = $("#reference-pixels"); const lengthInput = $("#reference-length");
  const context = canvas.getContext("2d");
  let stream = null; let image = null; let points = []; let distance = null;

  const say = (text) => { status.textContent = text; };
  function stopCamera() { stream?.getTracks().forEach((track) => track.stop()); stream = null; video.hidden = true; captureButton.hidden = true; }

  function draw() { if (!image) return;
    context.drawImage(image, 0, 0, canvas.width, canvas.height);
    const scale = canvas.clientWidth ? canvas.width / canvas.clientWidth : 1;  // marcas del mismo tamaño en pantalla, sea cual sea la resolución
    context.lineWidth = 3 * scale; context.strokeStyle = "#ff7a3d"; context.fillStyle = "#ff7a3d";
    if (points.length === 2) { context.beginPath(); context.moveTo(points[0].x, points[0].y); context.lineTo(points[1].x, points[1].y); context.stroke(); }
    points.forEach((point, index) => { context.beginPath(); context.arc(point.x, point.y, 7 * scale, 0, 2 * Math.PI); context.fill();
      context.font = `bold ${16 * scale}px sans-serif`; context.fillText(index === 0 ? "0" : "fin", point.x + 10 * scale, point.y - 10 * scale); });
    if (distance !== null) { const mid = { x: (points[0].x + points[1].x) / 2, y: (points[0].y + points[1].y) / 2 };
      context.font = `bold ${18 * scale}px sans-serif`; const label = `${distance} px`; const width = context.measureText(label).width;
      context.fillStyle = "rgba(11,42,74,.85)"; context.fillRect(mid.x - width / 2 - 8 * scale, mid.y - 34 * scale, width + 16 * scale, 26 * scale);
      context.fillStyle = "#fff"; context.fillText(label, mid.x - width / 2, mid.y - 15 * scale); } }

  function showImage(source, width, height, origin) { image = source; canvas.width = width; canvas.height = height; canvas.hidden = false;
    points = []; distance = null; applyButton.disabled = true; resetButton.hidden = true; draw();
    say(`${origin}: ${width} × ${height} px. Haz clic en la marca 0 de la regla.`); }

  canvas.addEventListener("click", (event) => { if (!image) return;
    const rect = canvas.getBoundingClientRect();  // pantalla → píxeles reales de la imagen
    const point = { x: (event.clientX - rect.left) * canvas.width / rect.width, y: (event.clientY - rect.top) * canvas.height / rect.height };
    if (points.length === 2) { points = []; distance = null; }
    points.push(point); resetButton.hidden = false;
    if (points.length === 1) { applyButton.disabled = true; say("Ahora haz clic en la marca final de la regla (p. ej. 10 cm)."); }
    else { distance = Math.round(Math.hypot(points[1].x - points[0].x, points[1].y - points[0].y));
      applyButton.disabled = distance < 1;
      say(distance < 20 ? `${distance} px: demasiado corto para medir con precisión (mínimo 20 px). Usa un tramo más largo de la regla o acerca la cámara.`
                        : `Distancia: ${distance} px. Pulsa «Usar esta medida». Un tercer clic empieza de nuevo.`); }
    draw(); });

  async function listCameras() { try { const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput");
    const selected = cameraSelect.value; cameraSelect.replaceChildren(new Option("Cámara predeterminada", ""));
    devices.forEach((device, index) => cameraSelect.append(new Option(device.label || `Cámara ${index + 1}`, device.deviceId)));
    cameraSelect.value = selected; } catch { /* sin permiso aún: queda la predeterminada */ } }

  $("#measure-start-camera").addEventListener("click", async () => { stopCamera();
    if (!navigator.mediaDevices?.getUserMedia) { say("Este navegador no permite usar la cámara. Sube una foto."); return; }
    try { const deviceId = cameraSelect.value;
      stream = await navigator.mediaDevices.getUserMedia({ video: deviceId ? { deviceId: { exact: deviceId } } : true, audio: false });
      video.srcObject = stream; video.hidden = false; captureButton.hidden = false; await video.play(); await listCameras();
      say("Encuadra la regla como en los análisis y pulsa «Tomar foto»."); }
    catch (error) { stopCamera(); say(`${window.SmartShrimp.cameraErrorText(error)} También puedes subir una foto.`); } });

  captureButton.addEventListener("click", () => { if (!video.videoWidth) return;
    const frame = document.createElement("canvas"); frame.width = video.videoWidth; frame.height = video.videoHeight;
    frame.getContext("2d").drawImage(video, 0, 0); stopCamera(); showImage(frame, frame.width, frame.height, "Foto de la cámara"); });

  // La foto de la regla pasa la misma validación que las imágenes de análisis: si no sirve para analizar, tampoco
  // sirve para calibrar (sus píxeles por cm no corresponderían a los análisis).
  const minSide = Number(panel.dataset.minImageSide) || 0;
  $("#measure-file").addEventListener("change", async (event) => { const file = event.target.files[0]; if (!file) return; stopCamera();
    const check = await window.SmartShrimp.validateImageFile(file, { minSide });
    if (check.ok) showImage(check.bitmap, check.bitmap.width, check.bitmap.height, "Foto subida"); else say(check.message);
    event.target.value = ""; });

  resetButton.addEventListener("click", () => { points = []; distance = null; applyButton.disabled = true; draw(); say("Haz clic en la marca 0 de la regla."); });

  // Resolución de la imagen medida: los píxeles solo valen para imágenes de ese mismo tamaño
  // (calibration.js la borra si después se escriben los píxeles a mano).
  const widthInput = $("#reference-image-width"); const heightInput = $("#reference-image-height");

  applyButton.addEventListener("click", () => { if (distance === null) return;
    pixelsInput.value = String(distance); widthInput.value = String(canvas.width); heightInput.value = String(canvas.height);
    pixelsInput.dispatchEvent(new Event("input", { bubbles: true }));  // actualiza la vista previa de la escala
    close(); if (!lengthInput.value) { lengthInput.focus(); } });

  function close() { stopCamera(); panel.hidden = true; openButton.hidden = false; }
  $("#measure-close").addEventListener("click", close);
  openButton.addEventListener("click", () => { panel.hidden = false; openButton.hidden = true; say("Elige cómo obtener la imagen de la regla."); listCameras(); });
  window.addEventListener("resize", draw);
  window.addEventListener("pagehide", stopCamera);
  openButton.hidden = false;  // solo se ofrece si este script cargó
})();
