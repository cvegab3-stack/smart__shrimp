"use strict";
(() => {
  const root = document.querySelector("#user-management"); if (!root) return; const list = document.querySelector("#user-list"); const form = document.querySelector("#user-create-form"); const message = document.querySelector("#user-message");
  const csrf = () => document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("csrftoken="))?.split("=").slice(1).join("=");
  const LABELS = { username: "Usuario", password: "Contraseña", role: "Rol", first_name: "Nombre", last_name: "Apellido", email: "Correo", is_active: "Estado" };
  // Convierte la respuesta de error de DRF ({campo: [mensajes]} o {detail}) en un texto legible; nunca muestra "{}".
  function describeError(data, status) { if (typeof data?.detail === "string") return data.detail;
    const parts = Object.entries(data || {}).map(([field, value]) => { const text = [].concat(value).join(" "); return LABELS[field] ? `${LABELS[field]}: ${text}` : text; });
    return parts.length ? parts.join(" · ") : `El servidor no pudo completar la operación (HTTP ${status}). Inténtalo de nuevo o revisa la ventana de Django.`; }
  async function api(url, method = "GET", body) { const response = await fetch(url, { method, credentials: "same-origin", headers: body ? { "Content-Type": "application/json", "X-CSRFToken": csrf() || "" } : {}, body: body ? JSON.stringify(body) : undefined }); const data = await response.json().catch(() => null); if (!response.ok) throw new Error(describeError(data, response.status)); return data; }
  const count = document.querySelector("#user-count");
  const ROLE_NAMES = { operador: "Operador", control_calidad: "Control de calidad", supervisor: "Supervisor", administrador: "Administrador" };
  const ICONS = {  // SVG fijos del código (no contienen datos de usuario)
    key: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="M10.8 12.2 20 3M16 7l3 3M14 9l2 2"/></svg>',
    lock: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
  };
  // Crea un elemento con clase y texto; el texto siempre va por textContent (los nombres de usuario no se interpretan como HTML).
  function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
  function button(text, onClick, { className = "btn btn-secondary", icon } = {}) { const node = el("button", className); node.type = "button";
    if (icon) node.insertAdjacentHTML("beforeend", ICONS[icon]); node.append(el("span", "", text)); node.addEventListener("click", onClick); return node; }
  // Columna "Contraseña": quién y cuándo la cambió por última vez. Nunca se muestra la contraseña (solo existe su hash).
  function passwordStatus(change) { if (!change) return "Sin cambios desde su creación";
    const when = new Date(change.at).toLocaleString("es-EC", { dateStyle: "short", timeStyle: "short" });
    return change.by === "usuario" ? `Cambiada por el usuario · ${when}` : `Asignada por ${change.actor || "el administrador"} · ${when}`; }
  function passwordField(id, labelText) { const field = el("div", "field"); const label = el("label", "", labelText); const input = el("input");
    input.type = "password"; input.id = id; input.autocomplete = "new-password"; input.required = true; label.htmlFor = id; field.append(label, input); return { field, input }; }
  // Panel bajo la cuenta para que el administrador asigne una contraseña nueva (el ojo lo añade password_toggle.js).
  function passwordRow(user, columns) { const row = el("tr", "password-row"); const cell = el("td"); cell.colSpan = columns;
    const panel = el("form", "password-panel"); panel.noValidate = true;
    const head = el("div", "password-panel-head"); head.insertAdjacentHTML("beforeend", `<span class="password-panel-icon">${ICONS.lock}</span>`);
    const titles = el("div"); titles.append(el("h3", "", "Cambiar contraseña"), el("p", "", `Cuenta: ${user.username}`)); head.append(titles);
    const first = passwordField(`set-password-${user.id}`, "Nueva contraseña"); const second = passwordField(`confirm-password-${user.id}`, "Confirmar contraseña");
    const fields = el("div", "password-panel-fields"); fields.append(first.field, second.field);
    const hint = el("p", "password-panel-hint", "Usa al menos 8 caracteres, evita contraseñas comunes, solo números o datos personales.");
    const status = el("div", "password-panel-error"); status.setAttribute("role", "alert");
    const save = el("button", "btn btn-teal", "Guardar contraseña"); save.type = "submit";
    const actions = el("div", "password-panel-actions"); actions.append(button("Cancelar", () => row.remove()), save);
    panel.addEventListener("submit", async (event) => { event.preventDefault(); status.textContent = "";
      if (!first.input.value) { status.textContent = "Escribe la nueva contraseña."; first.input.focus(); return; }
      if (first.input.value !== second.input.value) { status.textContent = "Las contraseñas no coinciden."; second.input.focus(); return; }
      save.disabled = true;
      try { await api(`/api/accounts/users/${user.id}/password/`, "POST", { password: first.input.value }); await loadUsers(); message.textContent = `Contraseña de ${user.username} actualizada.`; }
      catch (error) { status.textContent = error.message; save.disabled = false; } });
    panel.append(head, fields, hint, status, actions); cell.append(panel); row.append(cell); return row; }
  function userCell(user) { const cell = el("td"); const box = el("div", "account-user");
    box.append(el("span", "account-avatar", user.username.slice(0, 2).toUpperCase()), el("span", "account-name", user.username)); cell.append(box); return cell; }
  async function loadUsers() { try { const users = await api("/api/accounts/users/");
    if (count) { count.hidden = false; count.textContent = `${users.length} ${users.length === 1 ? "cuenta" : "cuentas"}`; }
    if (!users.length) { list.textContent = "No hay cuentas registradas."; return; }
    const headings = ["Usuario", "Rol", "Estado", "Contraseña", "Acciones"];
    const table = el("table", "accounts-table"); const tbody = el("tbody");
    users.forEach((user) => { const row = el("tr", "account-row");
      const role = el("td"); role.append(el("span", "role-pill", ROLE_NAMES[user.role] || user.role));
      const state = el("td"); state.append(el("span", `status-pill ${user.is_active ? "is-active" : "is-inactive"}`, user.is_active ? "Activa" : "Inactiva"));
      const password = el("td", "password-status-cell", passwordStatus(user.password_changed));
      const action = el("td"); const buttons = el("div", "account-actions");
      buttons.append(button(user.is_active ? "Desactivar" : "Activar", async () => { try { await api(`/api/accounts/users/${user.id}/`, "PATCH", { is_active: !user.is_active }); await loadUsers(); } catch (error) { message.textContent = error.message; } }));
      buttons.append(button("Cambiar contraseña", () => { const open = row.nextElementSibling?.classList.contains("password-row");
        list.querySelectorAll(".password-row").forEach((other) => other.remove());  // un solo panel abierto a la vez
        if (open) return; const panel = passwordRow(user, headings.length); row.after(panel); panel.querySelector("input").focus(); }, { icon: "key" }));
      action.append(buttons); row.append(userCell(user), role, state, password, action); tbody.append(row);
    });
    const thead = el("thead"); const heading = el("tr"); headings.forEach((value) => heading.append(el("th", "", value))); thead.append(heading); table.append(thead, tbody); list.replaceChildren(table);
  } catch (error) { list.textContent = error.message; } }
  form.addEventListener("submit", async (event) => { event.preventDefault(); const payload = { username: document.querySelector("#new-username").value, password: document.querySelector("#new-password").value, role: document.querySelector("#new-role").value, first_name: document.querySelector("#new-first-name").value, last_name: document.querySelector("#new-last-name").value, email: document.querySelector("#new-email").value };
    try { await api("/api/accounts/users/", "POST", payload); form.reset(); message.textContent = "Usuario creado."; await loadUsers(); } catch (error) { message.textContent = error.message; }
  }); loadUsers();
})();
