"use strict";
(() => {
  const root = document.querySelector("#user-management"); if (!root) return; const list = document.querySelector("#user-list"); const form = document.querySelector("#user-create-form"); const message = document.querySelector("#user-message");
  const csrf = () => document.cookie.split(";").map((part) => part.trim()).find((part) => part.startsWith("csrftoken="))?.split("=").slice(1).join("=");
  async function api(url, method = "GET", body) { const response = await fetch(url, { method, credentials: "same-origin", headers: body ? { "Content-Type": "application/json", "X-CSRFToken": csrf() || "" } : {}, body: body ? JSON.stringify(body) : undefined }); const data = await response.json().catch(() => ({})); if (!response.ok) throw new Error(data.detail || JSON.stringify(data)); return data; }
  async function loadUsers() { try { const users = await api("/api/accounts/users/"); if (!users.length) { list.textContent = "No hay cuentas registradas."; return; }
    const table = document.createElement("table"); const tbody = document.createElement("tbody");
    users.forEach((user) => { const row = document.createElement("tr"); [user.username, user.role.replaceAll("_", " "), user.is_active ? "Activa" : "Inactiva"].forEach((value) => { const cell = document.createElement("td"); cell.textContent = value; row.append(cell); });
      const action = document.createElement("td"); const button = document.createElement("button"); button.className = "btn btn-secondary"; button.type = "button"; button.textContent = user.is_active ? "Desactivar" : "Activar";
      button.addEventListener("click", async () => { try { await api(`/api/accounts/users/${user.id}/`, "PATCH", { is_active: !user.is_active }); await loadUsers(); } catch (error) { message.textContent = error.message; } }); action.append(button); row.append(action); tbody.append(row);
    });
    const thead = document.createElement("thead"); const heading = document.createElement("tr"); ["Usuario", "Rol", "Estado", ""].forEach((value) => { const cell = document.createElement("th"); cell.textContent = value; heading.append(cell); }); thead.append(heading); table.append(thead, tbody); list.replaceChildren(table);
  } catch (error) { list.textContent = error.message; } }
  form.addEventListener("submit", async (event) => { event.preventDefault(); const payload = { username: document.querySelector("#new-username").value, password: document.querySelector("#new-password").value, role: document.querySelector("#new-role").value, first_name: document.querySelector("#new-first-name").value, last_name: document.querySelector("#new-last-name").value, email: document.querySelector("#new-email").value };
    try { await api("/api/accounts/users/", "POST", payload); form.reset(); message.textContent = "Usuario creado."; await loadUsers(); } catch (error) { message.textContent = error.message; }
  }); loadUsers();
})();
