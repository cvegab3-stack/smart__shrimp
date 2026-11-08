"use strict";
(() => {
  const calibrationForm = document.querySelector("#calibration-form"); const thresholdForm = document.querySelector("#threshold-form"); if (!calibrationForm && !thresholdForm) return;
  const CATEGORIES = [["pequeno", "Pequeño"], ["mediano", "Mediano"], ["grande", "Grande"]];
  const post = (url, body) => window.SmartShrimp.request(url, { method: "POST", body });
  function show(element, text, ok) { element.textContent = text; element.className = `alert ${ok ? "alert-success" : "alert-error"}`; }

  // Medidas y confianzas nunca son negativas: no se puede escribir "-", "+" ni notación científica ("e"),
  // y un valor negativo pegado se descarta.
  document.querySelectorAll('#calibration-form input[type="number"], #threshold-form input[type="number"]').forEach((input) => {
    input.addEventListener("keydown", (event) => { if (["-", "+", "e", "E"].includes(event.key)) event.preventDefault(); });
    input.addEventListener("input", () => { if (input.value !== "" && Number(input.value) < 0) input.value = ""; });
  });

  const number = (selector) => { const raw = document.querySelector(selector).value.trim(); return raw === "" ? null : Number(raw); };
  // Mismos valores que Calibration en apps/analysis/models.py.
  const MIN_REFERENCE_PIXELS = 20; const PLAUSIBLE_PX_PER_CM = [5, 500];
  const fmt = (value) => Number(value.toFixed(2)).toLocaleString("es-EC");

  // Vista previa de la escala mientras se escribe, y aviso si no es verosímil para fotografiar camarones.
  const preview = document.querySelector("#scale-preview"); let confirmedScale = null;
  function scaleWarning(length, pixels) { const perCm = pixels / length;
    if (perCm < PLAUSIBLE_PX_PER_CM[0] || perCm > PLAUSIBLE_PX_PER_CM[1]) return `La escala de ${fmt(perCm)} px por cm es poco realista para fotografiar camarones. Comprueba que los píxeles corresponden a la regla en una foto de esta cámara.`;
    return null; }
  function updatePreview() { if (!preview) return; const length = number("#reference-length"); const pixels = number("#reference-pixels"); confirmedScale = null;
    if (!(length > 0) || !(pixels > 0)) { preview.hidden = true; return; }
    const perCm = pixels / length; const warning = pixels >= MIN_REFERENCE_PIXELS ? scaleWarning(length, pixels) : null;
    preview.hidden = false; preview.classList.toggle("is-warning", Boolean(warning) || pixels < MIN_REFERENCE_PIXELS);
    const imageWidth = number("#reference-image-width"); const imageHeight = number("#reference-image-height");
    preview.textContent = `Escala: 1 cm = ${fmt(perCm)} px (1 px = ${fmt(10 / perCm)} mm). Un camarón que ocupe 300 px en la imagen mediría ${fmt(300 / perCm)} cm.`
      + (imageWidth && imageHeight ? ` Medida en una foto de ${imageWidth} × ${imageHeight} px: las imágenes analizadas deben tener esa misma resolución.` : " Resolución no registrada (usa 📏 para registrarla).")
      + (pixels < MIN_REFERENCE_PIXELS ? ` La referencia debe ocupar al menos ${MIN_REFERENCE_PIXELS} px.` : "") + (warning ? ` ${warning}` : ""); }
  // Píxeles escritos a mano (evento real del usuario): ya no corresponden a la foto medida con 📏, se olvida su
  // resolución. Se registra antes que la vista previa para que esta no muestre una resolución que ya no vale.
  document.querySelector("#reference-pixels")?.addEventListener("input", (event) => { if (event.isTrusted) {
    ["#reference-image-width", "#reference-image-height"].forEach((selector) => { const field = document.querySelector(selector); if (field) field.value = ""; }); } });
  ["#reference-length", "#reference-pixels"].forEach((selector) => document.querySelector(selector)?.addEventListener("input", updatePreview));
  // Mismas reglas que Calibration.clean en el servidor; aquí solo para avisar antes de enviar.
  function calibrationProblems(length, pixels, ranges) { const problems = [];
    if (!(length > 0)) problems.push("La medida de referencia debe ser mayor que 0 cm.");
    if (!(Number.isInteger(pixels) && pixels >= MIN_REFERENCE_PIXELS)) problems.push(`La medida equivalente debe ser un número entero de al menos ${MIN_REFERENCE_PIXELS} px: con menos, un error de 1 px cambia todas las longitudes más de un 5 %.`);
    const bounds = [];
    CATEGORIES.forEach(([key, name]) => { const { min_cm: low, max_cm: high } = ranges[key];
      if (low !== null && low < 0) problems.push(`${name}: el mínimo no puede ser negativo.`);
      if (high !== null && high <= 0) problems.push(`${name}: el máximo debe ser mayor que 0.`);
      if (low !== null && high !== null && low >= high) problems.push(`${name}: el mínimo debe ser menor que el máximo.`);
      bounds.push([name.toLowerCase(), low ?? -Infinity, high ?? Infinity]); });
    if (problems.length) return problems;
    for (let i = 0; i < bounds.length - 1; i += 1) { const [left, leftMin, leftMax] = bounds[i]; const [right, rightMin, rightMax] = bounds[i + 1];
      if (Math.max(leftMin, rightMin) < Math.min(leftMax, rightMax)) problems.push(`Los rangos de ${left} y ${right} se superponen.`);  // tocarse en el límite está permitido
      else if (leftMin > rightMin) problems.push(`El rango de ${left} debe ser menor que el de ${right}.`);
      else if (leftMax < rightMin) problems.push(`Hay un hueco entre ${left} y ${right}: las medidas de ${fmt(leftMax)} a ${fmt(rightMin)} cm quedan sin categoría.`); }  // límites null (±Infinity) nunca entran aquí
    return problems; }

  // Límites encadenados: el máximo de una categoría rellena el mínimo de la siguiente. Si el administrador edita ese
  // mínimo a mano deja de rellenarse; si lo vacía (o lo iguala al máximo anterior) vuelve a enlazarse.
  const LINKS = [["pequeno", "mediano", "Pequeño"], ["mediano", "grande", "Mediano"]];
  const gapWarning = document.createElement("div"); gapWarning.className = "alert alert-amber"; gapWarning.setAttribute("role", "status"); gapWarning.hidden = true;
  calibrationForm?.querySelector(".notice")?.before(gapWarning);
  function updateGapWarning() { const gaps = [];
    LINKS.forEach(([from, to]) => { const upper = number(`#${from}-max`); const lower = number(`#${to}-min`);
      if (upper !== null && lower !== null && lower > upper) gaps.push(`entre ${upper} y ${lower} cm (${from === "pequeno" ? "pequeño" : from} → ${to})`); });
    gapWarning.hidden = !gaps.length;
    gapWarning.textContent = gaps.length ? `Hay un hueco ${gaps.join(" y ")}: los camarones de esa medida quedarán sin categoría.` : ""; }
  LINKS.forEach(([from, to, name]) => { const source = document.querySelector(`#${from}-max`); const target = document.querySelector(`#${to}-min`); if (!source || !target) return;
    const help = document.createElement("small"); help.className = "field-help"; help.textContent = `Se completa con el máximo de ${name}; puedes editarlo.`; target.after(help);
    const relink = () => { target.dataset.linked = target.value === "" || target.value === source.value ? "1" : "0"; }; relink();
    source.addEventListener("input", () => { if (target.dataset.linked === "1") target.value = source.value; updateGapWarning(); });
    target.addEventListener("input", () => { relink(); updateGapWarning(); });
    target.addEventListener("change", () => { if (target.value === "" && source.value !== "") { target.value = source.value; relink(); updateGapWarning(); } });
  });

  calibrationForm?.addEventListener("submit", async (event) => { event.preventDefault(); const message = document.querySelector("#calibration-message"); const ranges = {};
    CATEGORIES.forEach(([key]) => { ranges[key] = { min_cm: number(`#${key}-min`), max_cm: number(`#${key}-max`) }; });
    const length = number("#reference-length"); const pixels = number("#reference-pixels");
    const problems = calibrationProblems(length, pixels, ranges); if (problems.length) { show(message, problems.join(" "), false); return; }
    // Escala inverosímil: no se bloquea (puede haber montajes raros), pero exige un segundo clic consciente.
    const warning = scaleWarning(length, pixels); const scaleKey = `${length}/${pixels}`;
    if (warning && confirmedScale !== scaleKey) { confirmedScale = scaleKey; message.textContent = `${warning} Si los valores son correctos, pulsa «Guardar nueva versión» otra vez para confirmar.`; message.className = "alert alert-amber"; return; }
    const imageWidth = number("#reference-image-width"); const imageHeight = number("#reference-image-height");  // de la herramienta 📏, o vacíos
    try { const data = await post("/api/calibration/", { reference_length_cm: length, reference_pixels: pixels, size_ranges: ranges, image_width: imageWidth, image_height: imageHeight }); show(message, `Calibración v${data.version} guardada. Los análisis previos conservan su versión.`, true); window.location.reload(); }
    catch (error) { show(message, error.message, false); }
  });
  // Historial: "Usar esta versión" pone en uso esa misma versión (sin copiarla). Pide un segundo clic.
  document.querySelectorAll("[data-activate-version]").forEach((button) => { const version = button.dataset.activateVersion;
    const note = button.parentElement.querySelector(".history-message"); let armed = false;
    button.addEventListener("click", async () => {
      if (!armed) { armed = true; button.textContent = `Confirmar: usar versión ${version}`; button.className = "btn btn-teal"; note.textContent = ""; return; }
      button.disabled = true;
      try { const data = await post(`/api/calibration/${version}/activate/`, {}); button.textContent = `Versión ${data.version} en uso`; window.location.reload(); }
      catch (error) { note.textContent = error.message; button.disabled = false; armed = false; button.textContent = "Usar esta versión"; button.className = "btn btn-secondary"; }
    });
    button.addEventListener("blur", () => { if (armed && !button.disabled) { armed = false; button.textContent = "Usar esta versión"; button.className = "btn btn-secondary"; } });
  });

  thresholdForm?.addEventListener("submit", async (event) => { event.preventDefault(); const message = document.querySelector("#threshold-message");
    const detection = number("#detection-threshold"); const condition = number("#condition-threshold");
    if ([detection, condition].some((v) => v === null || v < 0 || v > 1)) { show(message, "Las confianzas deben estar entre 0 y 1 (por ejemplo, 0.5).", false); return; }
    try { await post("/api/thresholds/", { detection_confidence: detection, visual_condition_confidence: condition }); show(message, "Umbrales guardados.", true); }
    catch (error) { show(message, error.message, false); }
  });
})();
