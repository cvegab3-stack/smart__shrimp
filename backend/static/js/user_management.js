"use strict";
(() => {
  const root = document.querySelector("#user-management"); if (!root) return; const list = document.querySelector("#user-list"); const form = document.querySelector("#user-create-form"); const message = document.querySelector("#user-message");
  const currentUserId = Number(root.dataset.currentUserId); const minLength = Number(root.dataset.passwordMin) || 8;
  // Nombre visible de cada campo en los mensajes de error ("Usuario: Ese nombre de usuario ya está registrado.").
  const LABELS = { username: "Usuario", password: "Contraseña", role: "Rol", first_name: "Nombre", last_name: "Apellido", email: "Correo", is_active: "Estado" };
  const api = (url, method = "GET", body) => window.SmartShrimp.request(url, { method, body, labels: LABELS });
  const count = document.querySelector("#user-count");
  const ROLE_NAMES = { operador: "Operador", control_calidad: "Control de calidad", supervisor: "Supervisor", administrador: "Administrador" };
  const ICONS = {  // SVG fijos del código (no contienen datos de usuario)
    key: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="8" cy="15" r="4"/><path d="M10.8 12.2 20 3M16 7l3 3M14 9l2 2"/></svg>',
    edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4zM13.5 6.5l4 4"/></svg>',
    lock: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>',
  };
  const { el } = window.SmartShrimp;  // common.js: el texto va por textContent, nunca como HTML
  // Aviso bajo «Crear usuario»: verde si salió bien, rojo si no.
  function say(text, ok = true) { message.textContent = text; message.className = `field-wide alert ${ok ? "alert-success" : "alert-error"}`; message.hidden = !text; }
  function button(text, onClick, { className = "btn btn-secondary", icon } = {}) { const node = el("button", className); node.type = "button";
    if (icon) node.insertAdjacentHTML("beforeend", ICONS[icon]); node.append(el("span", "", text)); node.addEventListener("click", onClick); return node; }
  // Columna "Contraseña": quién y cuándo la cambió por última vez. Nunca se muestra la contraseña (solo existe su hash).
  function passwordStatus(change) { if (!change) return "Sin cambios desde su creación";
    const when = new Date(change.at).toLocaleString("es-EC", { dateStyle: "short", timeStyle: "short" });
    return change.by === "usuario" ? `Cambiada por el usuario · ${when}` : `Asignada por ${change.actor || "el administrador"} · ${when}`; }
  function passwordField(id, labelText, confirmId) { const field = el("div", "field"); const label = el("label", "", labelText); const input = el("input");
    input.type = "password"; input.id = id; input.autocomplete = "new-password"; input.required = true; label.htmlFor = id;
    // La lista de reglas la añade password_rules.js al ver data-password-rules.
    if (confirmId) { input.dataset.passwordRules = String(minLength); input.dataset.passwordConfirm = `#${confirmId}`; }
    field.append(label, input); return { field, input }; }
  function textField(id, labelText, value, type = "text") { const field = el("div", "field"); const label = el("label", "", labelText); const input = el("input");
    input.type = type; input.id = id; input.value = value || ""; label.htmlFor = id; field.append(label, input); return { field, input }; }
  // Fila desplegable bajo una cuenta (editar o cambiar contraseña); solo una abierta a la vez.
  function panelRow(columns, build) { const row = el("tr", "password-row account-panel-row"); const cell = el("td"); cell.colSpan = columns;
    cell.append(build(row)); row.append(cell); return row; }
  function panelHead(icon, title, subtitle) { const head = el("div", "password-panel-head"); head.insertAdjacentHTML("beforeend", `<span class="password-panel-icon">${ICONS[icon]}</span>`);
    const titles = el("div"); titles.append(el("h3", "", title), el("p", "", subtitle)); head.append(titles); return head; }
  // Pulsar de nuevo el mismo botón cierra su panel; otro botón lo sustituye.
  function togglePanel(row, kind, build, columns) { const next = row.nextElementSibling; const open = next?.classList.contains("account-panel-row") && next.dataset.kind === kind;
    list.querySelectorAll(".account-panel-row").forEach((other) => other.remove());
    if (open) return; const panel = panelRow(columns, build); panel.dataset.kind = kind; row.after(panel); panel.querySelector("input")?.focus(); }
  // Panel bajo la cuenta para que el administrador asigne una contraseña nueva (el ojo lo añade password_toggle.js).
  function passwordPanel(user) { return (row) => {
    const panel = el("form", "password-panel"); panel.noValidate = true;
    const head = panelHead("lock", "Cambiar contraseña", `Cuenta: ${user.username}`);
    const first = passwordField(`set-password-${user.id}`, "Nueva contraseña", `confirm-password-${user.id}`); const second = passwordField(`confirm-password-${user.id}`, "Confirmar contraseña");
    const fields = el("div", "password-panel-fields"); fields.append(first.field, second.field);
    const hint = el("p", "password-panel-hint", "Al guardar, la cuenta se desbloquea. La contraseña no se muestra ni se guarda en claro.");
    const status = el("div", "password-panel-error"); status.setAttribute("role", "alert");
    const save = el("button", "btn btn-teal", "Guardar contraseña"); save.type = "submit";
    const actions = el("div", "password-panel-actions"); actions.append(button("Cancelar", () => row.remove()), save);
    panel.addEventListener("submit", async (event) => { event.preventDefault(); status.textContent = "";
      if (!first.input.value) { status.textContent = "Escribe la nueva contraseña."; first.input.focus(); return; }
      if (first.input.value !== second.input.value) { status.textContent = "Las contraseñas no coinciden."; second.input.focus(); return; }
      save.disabled = true;
      try { await api(`/api/accounts/users/${user.id}/password/`, "POST", { password: first.input.value }); await loadUsers(); say(`Contraseña de ${user.username} actualizada.`); }
      catch (error) { status.textContent = error.message; save.disabled = false; } });
    panel.append(head, fields, hint, status, actions); return panel; }; }
  // Panel "Editar": usuario, nombre, apellido, correo y rol. Solo se envían los campos que cambian.
  function editPanel(user, isSelf) { return (row) => {
    const panel = el("form", "password-panel"); panel.noValidate = true;
    const head = panelHead("edit", "Editar cuenta", `Cuenta: ${user.username}`);
    const inputs = { username: textField(`edit-username-${user.id}`, "Usuario", user.username), first_name: textField(`edit-first-${user.id}`, "Nombre", user.first_name),
      last_name: textField(`edit-last-${user.id}`, "Apellido", user.last_name), email: textField(`edit-email-${user.id}`, "Correo", user.email, "email") };
    const roleField = el("div", "field"); const roleLabel = el("label", "", "Rol"); const role = el("select"); role.id = `edit-role-${user.id}`; roleLabel.htmlFor = role.id;
    Object.entries(ROLE_NAMES).forEach(([value, text]) => { const option = el("option", "", text); option.value = value; option.selected = value === user.role; role.append(option); });
    roleField.append(roleLabel, role);
    if (isSelf) { role.disabled = true; roleField.append(el("small", "field-help", "No puedes cambiar tu propio rol; pídeselo a otro administrador.")); }
    const fields = el("div", "password-panel-fields"); Object.values(inputs).forEach(({ field }) => fields.append(field)); fields.append(roleField);
    const status = el("div", "password-panel-error"); status.setAttribute("role", "alert");
    const save = el("button", "btn btn-teal", "Guardar cambios"); save.type = "submit";
    const actions = el("div", "password-panel-actions"); actions.append(button("Cancelar", () => row.remove()), save);
    panel.addEventListener("submit", async (event) => { event.preventDefault(); status.textContent = "";
      const changes = {}; Object.entries(inputs).forEach(([key, { input }]) => { const value = input.value.trim(); if (value !== (user[key] || "")) changes[key] = value; });
      if (!isSelf && role.value !== user.role) changes.role = role.value;
      if ("username" in changes && !changes.username) { status.textContent = "El usuario no puede quedar vacío."; inputs.username.input.focus(); return; }
      if (!Object.keys(changes).length) { row.remove(); return; }
      save.disabled = true;
      try { await api(`/api/accounts/users/${user.id}/`, "PATCH", changes); await loadUsers(); say(`Cuenta ${changes.username || user.username} actualizada.`); }
      catch (error) { status.textContent = error.message; save.disabled = false; } });
    panel.append(head, fields, status, actions); return panel; }; }
  function userCell(user, isSelf) { const cell = el("td"); const box = el("div", "account-user"); const names = el("div", "account-names");
    names.append(el("span", "account-name", isSelf ? `${user.username} (tú)` : user.username));
    const detail = [[user.first_name, user.last_name].filter(Boolean).join(" "), user.email].filter(Boolean).join(" · ");
    if (detail) names.append(el("small", "account-detail", detail));
    box.append(el("span", "account-avatar", user.username.slice(0, 2).toUpperCase()), names); cell.append(box); return cell; }
  async function loadUsers() { try { const users = await api("/api/accounts/users/");
    if (count) { count.hidden = false; count.textContent = `${users.length} ${users.length === 1 ? "cuenta" : "cuentas"}`; }
    if (!users.length) { list.textContent = "No hay cuentas registradas."; return; }
    const headings = ["Usuario", "Rol", "Estado", "Contraseña", "Acciones"];
    const table = el("table", "accounts-table"); const tbody = el("tbody");
    const activeAdmins = users.filter((u) => u.is_active && u.role === "administrador").length;
    users.forEach((user) => { const row = el("tr", "account-row"); const isSelf = user.id === currentUserId;
      // Mismas reglas que el servidor (que las aplica igualmente): siempre un administrador activo y nadie se desactiva a sí mismo.
      const lastAdmin = user.is_active && user.role === "administrador" && activeAdmins <= 1;
      const role = el("td"); role.append(el("span", "role-pill", ROLE_NAMES[user.role] || user.role));
      const state = el("td"); state.append(el("span", `status-pill ${user.is_active ? "is-active" : "is-inactive"}`, user.is_active ? "Activa" : "Inactiva"));
      const password = el("td", "password-status-cell", passwordStatus(user.password_changed));
      const action = el("td"); const buttons = el("div", "account-actions");
      buttons.append(button("Editar", () => togglePanel(row, "edit", editPanel(user, isSelf), headings.length), { icon: "edit" }));
      const toggle = button(user.is_active ? "Desactivar" : "Activar", async () => {
        if (user.is_active && !window.confirm(`¿Desactivar la cuenta ${user.username}? No podrá iniciar sesión hasta que la actives de nuevo.`)) return;
        try { await api(`/api/accounts/users/${user.id}/`, "PATCH", { is_active: !user.is_active }); await loadUsers(); say(`Cuenta ${user.username} ${user.is_active ? "desactivada" : "activada"}.`); } catch (error) { say(error.message, false); } });
      if (user.is_active && (isSelf || lastAdmin)) { toggle.disabled = true; toggle.title = isSelf ? "No puedes desactivar tu propia cuenta." : "Es el único administrador activo: crea o activa otro antes de desactivarlo."; }
      buttons.append(toggle);
      buttons.append(button("Cambiar contraseña", () => togglePanel(row, "password", passwordPanel(user), headings.length), { icon: "key" }));
      action.append(buttons); row.append(userCell(user, isSelf), role, state, password, action); tbody.append(row);
    });
    const thead = el("thead"); const heading = el("tr"); headings.forEach((value) => heading.append(el("th", "", value))); thead.append(heading); table.append(thead, tbody); list.replaceChildren(table);
  } catch (error) { list.textContent = error.message; } }
  const createButton = document.querySelector("#create-user-button");
  form.addEventListener("submit", async (event) => { event.preventDefault(); if (createButton.disabled) return;
    const confirmInput = document.querySelector("#new-password-confirm");
    if (document.querySelector("#new-password").value !== confirmInput.value) { say("Las contraseñas no coinciden.", false); confirmInput.focus(); return; }
    const payload = { username: document.querySelector("#new-username").value, password: document.querySelector("#new-password").value, role: document.querySelector("#new-role").value, first_name: document.querySelector("#new-first-name").value, last_name: document.querySelector("#new-last-name").value, email: document.querySelector("#new-email").value };
    createButton.disabled = true; createButton.textContent = "Creando…";
    try { await api("/api/accounts/users/", "POST", payload); form.reset(); say(`Usuario ${payload.username} creado.`); await loadUsers(); } catch (error) { say(error.message, false); }
    finally { createButton.disabled = false; createButton.textContent = "Crear usuario"; }
  }); loadUsers();
})();
