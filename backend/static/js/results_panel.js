"use strict";
window.SmartShrimpResults = { render(container, detail) {
  const table = document.createElement("table"); const headers = ["ID de seguimiento", "Integridad", "Presentación", "Condición visual", "Longitud", "Tamaño", "Peso estimado"];
  const thead = document.createElement("thead"); const headRow = document.createElement("tr"); headers.forEach((label) => { const cell = document.createElement("th"); cell.textContent = label; headRow.append(cell); }); thead.append(headRow);
  const tbody = document.createElement("tbody"); (detail.results || []).forEach((row) => {
    const values = [row.track_id, row.integrity || "No disponible", row.presentation || "No disponible", row.visual_condition, row.length_cm == null ? "No disponible" : `${Number(row.length_cm).toFixed(2)} cm`, row.size_category || "No disponible", row.estimated_weight_g == null ? "No disponible · valor estimado" : `${Number(row.estimated_weight_g).toFixed(2)} g · valor estimado`];
    const tr = document.createElement("tr"); values.forEach((value) => { const cell = document.createElement("td"); cell.textContent = value; tr.append(cell); }); tbody.append(tr);
  });
  table.className = "data-table"; table.append(thead, tbody); const wrap = document.createElement("div"); wrap.className = "table-wrap"; wrap.append(table);
  const summary = document.createElement("p"); summary.textContent = `${detail.analysis.shrimp_count} camarones · ${detail.analysis.rejected_count} descartados · ${detail.analysis.status}.`; container.replaceChildren(summary, wrap);
} };
