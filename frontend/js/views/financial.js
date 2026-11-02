import { api } from "../api.js";
import { escapeHtml, formatDate } from "../ui.js";
import { isAdmin } from "../state.js";
import { getAllUsers, getUserName } from "../usersCache.js";
import { tabs } from "./financeAdvanced.js";

const LOSS_REASONS = { vol: "Vol", casse: "Casse", perte: "Perte" };

let lossFilters = { type: "", reason: "", person: "" };
let repairFilters = { type: "", person: "" };

export async function renderFinancial(app) {
  const [summary, tools] = await Promise.all([api.get("/agency-tools/financial-summary"), api.get("/agency-tools")]);
  await getAllUsers();
  draw(app, summary, tools);
}

function draw(app, summary, tools) {
  const lost = tools.filter((t) => t.status === "hors_service");
  const repairing = tools.filter((t) => t.status === "reparation");

  const lossTypes = [...new Set(lost.map((t) => t.type).filter(Boolean))].sort();
  const lossPeople = [...new Set(lost.map((t) => t.assigned_to_id).filter(Boolean))];
  const repairTypes = [...new Set(repairing.map((t) => t.type).filter(Boolean))].sort();
  const repairPeople = [...new Set(repairing.map((t) => t.assigned_to_id).filter(Boolean))];

  let filteredLost = lost;
  if (lossFilters.type) filteredLost = filteredLost.filter((t) => t.type === lossFilters.type);
  if (lossFilters.reason) filteredLost = filteredLost.filter((t) => t.loss_reason === lossFilters.reason);
  if (lossFilters.person) filteredLost = filteredLost.filter((t) => String(t.assigned_to_id) === lossFilters.person);

  let filteredRepair = repairing;
  if (repairFilters.type) filteredRepair = filteredRepair.filter((t) => t.type === repairFilters.type);
  if (repairFilters.person) filteredRepair = filteredRepair.filter((t) => String(t.assigned_to_id) === repairFilters.person);

  const lossValue = filteredLost.reduce((sum, t) => sum + (t.purchase_price || 0), 0);
  const recoverable = filteredLost.filter((t) => t.warranty_expiration_date && new Date(t.warranty_expiration_date) > new Date());
  const recoverableValue = recoverable.reduce((sum, t) => sum + (t.purchase_price || 0), 0);

  const repairValue = filteredRepair.reduce((sum, t) => sum + (t.purchase_price || 0), 0);

  const lossByReason = {};
  filteredLost.forEach((t) => {
    const key = t.loss_reason || "inconnu";
    lossByReason[key] = (lossByReason[key] || 0) + 1;
  });

  app.innerHTML = `
    <div class="section-header"><h1>Finances</h1></div>${tabs("/finances")}

    <div class="stat-grid">
      <div class="stat-tile">
        <div class="stat-value">${summary.total_value.toLocaleString("fr-FR")} €</div>
        <div class="stat-label">Valeur totale du parc</div>
      </div>
      <div class="stat-tile">
        <div class="stat-value">${summary.total_count}</div>
        <div class="stat-label">Nombre d'outils</div>
      </div>
    </div>

    <h3>Valeur par type d'outil</h3>
    <div class="table-scroll">
      <table class="simple-table">
        <thead><tr><th>Type</th><th>Nombre</th><th>Valeur</th></tr></thead>
        <tbody>
          ${summary.by_type.map((r) => `<tr><td>${escapeHtml(r.label)}</td><td>${r.count}</td><td>${r.total_value.toLocaleString("fr-FR")} €</td></tr>`).join("")}
        </tbody>
      </table>
    </div>

    ${
      isAdmin() && summary.by_agency
        ? `
    <h3>Valeur par agence</h3>
    <div class="table-scroll">
      <table class="simple-table">
        <thead><tr><th>Agence</th><th>Nombre</th><th>Valeur</th></tr></thead>
        <tbody>
          ${summary.by_agency.map((r) => `<tr><td>${escapeHtml(r.label)}</td><td>${r.count}</td><td>${r.total_value.toLocaleString("fr-FR")} €</td></tr>`).join("")}
        </tbody>
      </table>
    </div>`
        : ""
    }

    <h3>Pertes estimées</h3>
    <div class="stat-grid">
      <div class="stat-tile stat-red">
        <div class="stat-value">${lossValue.toLocaleString("fr-FR")} €</div>
        <div class="stat-label">Valeur estimée</div>
      </div>
      <div class="stat-tile">
        <div class="stat-value">${filteredLost.length}</div>
        <div class="stat-label">Outils concernés</div>
      </div>
      <div class="stat-tile stat-green">
        <div class="stat-value">${recoverableValue.toLocaleString("fr-FR")} €</div>
        <div class="stat-label">Récupérable sous garantie</div>
      </div>
    </div>
    <div class="card-meta" style="margin-bottom:0.75rem;">
      ${Object.entries(lossByReason)
        .map(([k, v]) => `<span class="badge badge-red">${LOSS_REASONS[k] || k} : ${v}</span>`)
        .join("")}
    </div>
    <div class="filter-bar">
      <select id="loss-type-filter">
        <option value="">Tous types</option>
        ${lossTypes.map((t) => `<option value="${escapeHtml(t)}" ${t === lossFilters.type ? "selected" : ""}>${escapeHtml(t)}</option>`).join("")}
      </select>
      <select id="loss-reason-filter">
        <option value="">Tout motif</option>
        ${Object.entries(LOSS_REASONS)
          .map(([k, v]) => `<option value="${k}" ${k === lossFilters.reason ? "selected" : ""}>${v}</option>`)
          .join("")}
      </select>
      <select id="loss-person-filter">
        <option value="">Toutes personnes</option>
        ${lossPeople.map((id) => `<option value="${id}" ${String(id) === lossFilters.person ? "selected" : ""}>${escapeHtml(getUserName(id))}</option>`).join("")}
      </select>
    </div>
    <div class="table-scroll">
      <table class="simple-table">
        <thead><tr><th>Outil</th><th>Type</th><th>Motif</th><th>Personne</th><th>Achat</th><th>Garantie</th><th>Valeur</th></tr></thead>
        <tbody>
          ${filteredLost
            .map(
              (t) => `<tr>
            <td>${escapeHtml(t.name)}</td>
            <td>${escapeHtml(t.type || "-")}</td>
            <td>${LOSS_REASONS[t.loss_reason] || t.loss_reason || "-"}</td>
            <td>${escapeHtml(t.assigned_to_id ? getUserName(t.assigned_to_id) : "-")}</td>
            <td>${formatDate(t.purchase_date)}</td>
            <td>${formatDate(t.warranty_expiration_date)}</td>
            <td>${(t.purchase_price || 0).toLocaleString("fr-FR")} €</td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>
    </div>

    <h3>Outils en réparation</h3>
    <div class="stat-grid">
      <div class="stat-tile">
        <div class="stat-value">${repairValue.toLocaleString("fr-FR")} €</div>
        <div class="stat-label">Valeur immobilisée</div>
      </div>
      <div class="stat-tile">
        <div class="stat-value">${filteredRepair.length}</div>
        <div class="stat-label">Outils concernés</div>
      </div>
    </div>
    <div class="filter-bar">
      <select id="repair-type-filter">
        <option value="">Tous types</option>
        ${repairTypes.map((t) => `<option value="${escapeHtml(t)}" ${t === repairFilters.type ? "selected" : ""}>${escapeHtml(t)}</option>`).join("")}
      </select>
      <select id="repair-person-filter">
        <option value="">Toutes personnes</option>
        ${repairPeople.map((id) => `<option value="${id}" ${String(id) === repairFilters.person ? "selected" : ""}>${escapeHtml(getUserName(id))}</option>`).join("")}
      </select>
    </div>
    <div class="table-scroll">
      <table class="simple-table">
        <thead><tr><th>Outil</th><th>Type</th><th>Personne</th><th>Dernier contrôle</th><th>Valeur</th></tr></thead>
        <tbody>
          ${filteredRepair
            .map(
              (t) => `<tr>
            <td>${escapeHtml(t.name)}</td>
            <td>${escapeHtml(t.type || "-")}</td>
            <td>${escapeHtml(t.assigned_to_id ? getUserName(t.assigned_to_id) : "-")}</td>
            <td>${formatDate(t.last_control_date)}</td>
            <td>${(t.purchase_price || 0).toLocaleString("fr-FR")} €</td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>
    </div>

    <h3>Achats récents</h3>
    <div class="table-scroll">
      <table class="simple-table">
        <thead><tr><th>Outil</th><th>Type</th><th>Prix</th><th>Date</th></tr></thead>
        <tbody>
          ${summary.recent_purchases
            .map(
              (p) => `<tr>
            <td>${escapeHtml(p.name)}</td>
            <td>${escapeHtml(p.type || "-")}</td>
            <td>${(p.purchase_price || 0).toLocaleString("fr-FR")} €</td>
            <td>${formatDate(p.purchase_date)}</td>
          </tr>`
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;

  document.getElementById("loss-type-filter").addEventListener("change", (e) => {
    lossFilters.type = e.target.value;
    draw(app, summary, tools);
  });
  document.getElementById("loss-reason-filter").addEventListener("change", (e) => {
    lossFilters.reason = e.target.value;
    draw(app, summary, tools);
  });
  document.getElementById("loss-person-filter").addEventListener("change", (e) => {
    lossFilters.person = e.target.value;
    draw(app, summary, tools);
  });
  document.getElementById("repair-type-filter").addEventListener("change", (e) => {
    repairFilters.type = e.target.value;
    draw(app, summary, tools);
  });
  document.getElementById("repair-person-filter").addEventListener("change", (e) => {
    repairFilters.person = e.target.value;
    draw(app, summary, tools);
  });
}
