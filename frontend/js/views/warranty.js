import { api } from "../api.js";
import { escapeHtml, formatDate } from "../ui.js";

const PAGE_SIZE = 200;
let filters = { q: "", type: "", status: "" };
let limit = PAGE_SIZE;

function warrantyStatus(tool) {
  if (!tool.warranty_expiration_date) return "none";
  return new Date(tool.warranty_expiration_date) > new Date() ? "active" : "expired";
}

export async function renderWarranty(app) {
  const tools = await api.get("/agency-tools");
  draw(app, tools);
}

function draw(app, tools) {
  const active = tools.filter((t) => warrantyStatus(t) === "active");
  const expired = tools.filter((t) => warrantyStatus(t) === "expired");
  const none = tools.filter((t) => warrantyStatus(t) === "none");

  const types = [...new Set(tools.map((t) => t.type).filter(Boolean))].sort();

  let filtered = tools;
  if (filters.q) {
    const q = filters.q.toLowerCase();
    filtered = filtered.filter((t) => t.name.toLowerCase().includes(q) || t.unique_code.toLowerCase().includes(q));
  }
  if (filters.type) filtered = filtered.filter((t) => t.type === filters.type);
  if (filters.status) filtered = filtered.filter((t) => warrantyStatus(t) === filters.status);

  filtered = [...filtered].sort((a, b) => {
    if (!a.warranty_expiration_date && !b.warranty_expiration_date) return 0;
    if (!a.warranty_expiration_date) return 1;
    if (!b.warranty_expiration_date) return -1;
    return new Date(a.warranty_expiration_date) - new Date(b.warranty_expiration_date);
  });

  app.innerHTML = `
    <div class="section-header"><h1>Garanties</h1></div>

    <div class="stat-grid">
      <div class="stat-tile stat-green">
        <div class="stat-value">${active.length}</div>
        <div class="stat-label">En garantie</div>
      </div>
      <div class="stat-tile stat-red">
        <div class="stat-value">${expired.length}</div>
        <div class="stat-label">Garantie expirée</div>
      </div>
      <div class="stat-tile stat-gray">
        <div class="stat-value">${none.length}</div>
        <div class="stat-label">Non renseignée</div>
      </div>
    </div>

    <div class="filter-bar">
      <input type="text" id="w-search" placeholder="Recherche" value="${escapeHtml(filters.q)}"/>
      <select id="w-type">
        <option value="">Tous types</option>
        ${types.map((t) => `<option value="${escapeHtml(t)}" ${t === filters.type ? "selected" : ""}>${escapeHtml(t)}</option>`).join("")}
      </select>
      <select id="w-status">
        <option value="">Tout statut</option>
        <option value="active" ${filters.status === "active" ? "selected" : ""}>En garantie</option>
        <option value="expired" ${filters.status === "expired" ? "selected" : ""}>Expirée</option>
        <option value="none" ${filters.status === "none" ? "selected" : ""}>Non renseignée</option>
      </select>
    </div>

    <div class="table-scroll">
      <table class="simple-table">
        <thead><tr><th>Outil</th><th>Type</th><th>Achat</th><th>Fin de garantie</th><th>Statut</th></tr></thead>
        <tbody>
          ${filtered
            .slice(0, limit)
            .map((t) => {
              const ws = warrantyStatus(t);
              const badge =
                ws === "active"
                  ? '<span class="badge badge-green"><span class="dot"></span>En garantie</span>'
                  : ws === "expired"
                  ? '<span class="badge badge-red"><span class="dot"></span>Expirée</span>'
                  : '<span class="badge badge-gray"><span class="dot"></span>Non renseignée</span>';
              return `<tr>
                <td>${escapeHtml(t.name)}</td>
                <td>${escapeHtml(t.type || "-")}</td>
                <td>${formatDate(t.purchase_date)}</td>
                <td>${formatDate(t.warranty_expiration_date)}</td>
                <td>${badge}</td>
              </tr>`;
            })
            .join("")}
        </tbody>
      </table>
    </div>
    ${filtered.length > limit ? `<div class="load-more"><button class="btn" id="w-more">Afficher plus (${limit} sur ${filtered.length})</button></div>` : ""}
  `;

  document.getElementById("w-more")?.addEventListener("click", () => {
    limit += PAGE_SIZE;
    draw(app, tools);
  });

  document.getElementById("w-search").addEventListener("input", (e) => {
    filters.q = e.target.value;
    draw(app, tools);
  });
  document.getElementById("w-type").addEventListener("change", (e) => {
    filters.type = e.target.value;
    draw(app, tools);
  });
  document.getElementById("w-status").addEventListener("change", (e) => {
    filters.status = e.target.value;
    draw(app, tools);
  });
}
