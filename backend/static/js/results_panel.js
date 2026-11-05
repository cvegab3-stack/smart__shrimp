"use strict";
// Muestra el resultado de un análisis en lenguaje de planta. Lo usan el resultado inmediato (Nuevo análisis) y la
// página de detalle (Mis lotes). Los datos llegan ya traducidos desde apps/results/services/presentation_service.py.
// Todo el texto se inserta con textContent: nada de lo recibido se interpreta como HTML.
(() => {
  const el = (tag, className, text) => { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; };

  // Dibuja los recuadros sobre la imagen. bbox viene en píxeles de la imagen original: se pasa a porcentajes para
  // que encajen a cualquier tamaño en pantalla.
  function drawBoxes(figure, boxes) { const image = figure.querySelector("img");
    const place = () => { if (!image.naturalWidth) return; figure.querySelectorAll(".snapshot-box").forEach((box) => box.remove());
      (boxes || []).forEach(({ bbox, label, size_key: sizeKey }) => { if (!Array.isArray(bbox) || bbox.length !== 4) return;
        const [x1, y1, x2, y2] = bbox; const box = el("div", `snapshot-box size-${sizeKey || "otro"}`);
        Object.assign(box.style, { left: `${(x1 / image.naturalWidth) * 100}%`, top: `${(y1 / image.naturalHeight) * 100}%`,
          width: `${((x2 - x1) / image.naturalWidth) * 100}%`, height: `${((y2 - y1) / image.naturalHeight) * 100}%` });
        box.append(el("span", "snapshot-label", label)); figure.append(box); }); };
    if (image.complete) place(); else image.addEventListener("load", place, { once: true }); }

  // Aviso si la imagen no tiene la resolución en que se midió la calibración: sus píxeles no equivalen a los mismos cm.
  function checkResolution(figure, expected) { const image = figure.querySelector("img"); if (!image || !Array.isArray(expected)) return;
    const check = () => { const [width, height] = expected; if (!image.naturalWidth || (image.naturalWidth === width && image.naturalHeight === height)) return;
      if (figure.parentElement?.querySelector(".resolution-warning")) return;
      const warning = el("div", "alert alert-amber resolution-warning", `Esta imagen mide ${image.naturalWidth} × ${image.naturalHeight} px, pero la calibración se midió en una de ${width} × ${height} px: las longitudes y los tamaños no son fiables. Usa la misma cámara y resolución que en la calibración.`);
      warning.setAttribute("role", "status"); figure.before(warning); };
    if (image.complete) check(); else image.addEventListener("load", check, { once: true }); }

  function snapshotFigure(summary) { const figure = el("figure", "snapshot");
    if (!summary.snapshot_url) { figure.append(el("p", "snapshot-empty", "Este análisis no tiene imagen guardada.")); return figure; }
    const image = el("img"); image.alt = "Imagen analizada con un recuadro sobre cada camarón detectado"; image.src = `${summary.snapshot_url}?t=${Date.now()}`;
    figure.append(image); drawBoxes(figure, summary.boxes); queueMicrotask(() => checkResolution(figure, summary.calibration_resolution));
    if (summary.source === "video") figure.append(el("figcaption", "", "Último fotograma con camarones de la grabación."));
    return figure; }

  function render(container, detail, { elapsedMs } = {}) { const summary = detail.summary; const parts = [];
    const head = el("div", "result-total"); head.append(el("strong", "", String(summary.total)), el("span", "", summary.total === 1 ? "camarón detectado" : "camarones detectados"));
    if (elapsedMs !== undefined) head.append(el("small", "result-time", `Analizado en ${(elapsedMs / 1000).toLocaleString("es-EC", { maximumFractionDigits: 1 })} s`));
    parts.push(head);
    if (summary.total) { // los contadores por tamaño solo tienen sentido si hubo camarones
      const counts = el("div", "size-counts"); summary.counts.forEach(({ key, name, count }) => { const chip = el("span", `size-chip size-${key}`); chip.append(el("strong", "", String(count)), el("span", "", name)); counts.append(chip); });
      parts.push(counts); }
    else { parts.push(el("div", "alert alert-info", summary.rejected ? "No se contó ningún camarón." : "No se detectó ningún camarón. Comprueba que se vean bien y que la imagen no esté borrosa ni oscura.")); }
    if (summary.length_avg) parts.push(el("p", "result-lengths", `Longitud promedio ${summary.length_avg} · mínima ${summary.length_min} · máxima ${summary.length_max}`));
    if (summary.close_up) parts.push(el("div", "alert alert-amber", `${summary.close_up === 1 ? "1 camarón ocupa" : `${summary.close_up} camarones ocupan`} casi toda la imagen (foto demasiado cercana): se ${summary.close_up === 1 ? "cuenta" : "cuentan"}, pero su medida puede no ser fiable. Aleja la cámara hasta la posición de la calibración.`));
    if (summary.counts.some((c) => c.key === "fuera")) parts.push(el("p", "result-note", "«Fuera de rango»: su longitud no entra en ningún rango de tamaño de la calibración vigente."));
    if (summary.rejected_text) parts.push(el("p", "result-note", summary.rejected_text));
    parts.push(snapshotFigure(summary));
    if (summary.rows.length) { const headers = ["Camarón", "Longitud", "Tamaño"]; if (summary.show_condition) headers.push("Condición visual"); if (summary.show_weight) headers.push("Peso estimado");
      const table = el("table", "data-table result-table"); const headRow = el("tr"); headers.forEach((label) => headRow.append(el("th", "", label)));
      const thead = el("thead"); thead.append(headRow); const tbody = el("tbody");
      summary.rows.forEach((row) => { const tr = el("tr"); tr.append(el("td", "", `Camarón ${row.number}`), el("td", "", row.close_up ? `${row.length} (primer plano, poco fiable)` : row.length));
        const size = el("td"); size.append(el("span", `size-chip size-${row.size_key}`, row.size)); tr.append(size);
        if (summary.show_condition) tr.append(el("td", "", row.condition)); if (summary.show_weight) tr.append(el("td", "", row.weight)); tbody.append(tr); });
      table.append(thead, tbody); const wrap = el("div", "table-wrap"); wrap.append(table); parts.push(wrap); }
    if (!summary.show_condition || !summary.show_weight) parts.push(el("p", "result-note", "Condición visual y peso: aún no disponibles (el sistema todavía no tiene esos modelos entrenados)."));
    container.replaceChildren(...parts); }

  // Página de detalle: dibuja los recuadros de las figuras renderizadas por el servidor.
  document.querySelectorAll("figure.snapshot[data-boxes-id]").forEach((figure) => {
    const data = document.getElementById(figure.dataset.boxesId); drawBoxes(figure, data ? JSON.parse(data.textContent) : []);
    const resolution = figure.dataset.calibrationWidth ? [Number(figure.dataset.calibrationWidth), Number(figure.dataset.calibrationHeight)] : null;
    checkResolution(figure, resolution); });

  window.SmartShrimpResults = { render, drawBoxes, checkResolution };
})();
