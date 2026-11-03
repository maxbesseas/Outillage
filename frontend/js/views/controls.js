import { api, ApiError } from "../api.js";
import { escapeHtml, formatDate, toast } from "../ui.js";
import { isAdmin } from "../state.js";
import { openInspectionForm } from "../inspectionForm.js";

const STATUS = {
  overdue: ["red", "En retard"],
  never: ["orange", "Jamais contrôlé"],
  soon: ["blue", "Bientôt"],
};
const KIND_LABEL = { agency: "Outil d'agence", epi: "EPI", personal: "Outil personnel" };

const PAGE_SIZE = 100;
let filter = { kind: "", status: "" };

function card(item) {
  const [color, label] = STATUS[item.status] || ["gray", item.status];
  const when =
    item.status === "never"
      ? "Jamais contrôlé"
      : item.days_left < 0
        ? `Échéance dépassée de ${-item.days_left} jour(s) (${formatDate(item.due)})`
        : `Échéance dans ${item.days_left} jour(s) (${formatDate(item.due)})`;
  return `
    <div class="card" data-kind="${item.kind}" data-id="${item.id}">
      <div class="card-row">
        <div class="card-title">${escapeHtml(item.name)}</div>
        <span class="badge badge-${color}"><span class="dot"></span>${label}</span>
      </div>
      <div class="card-sub">${escapeHtml(KIND_LABEL[item.kind])} · ${escapeHtml(item.type || "-")} · ${escapeHtml(item.code)}</div>
      <div class="card-meta"><span>${escapeHtml(when)}</span><span>Périodicité : ${item.periodicity_days} j</span></div>
      <div class="card-actions"><button class="btn btn-sm btn-primary" data-action="inspect">Contrôler</button></div>
    </div>`;
}

export async function renderControls(app) {
  const params = new URLSearchParams();
  if (filter.kind) params.set("kind", filter.kind);
  if (filter.status) params.set("status_filter", filter.status);
  const { items, counts } = await api.get(`/inspections/due?${params}`);

  app.innerHTML = `
    <div class="section-header">
      <h1>Contrôles à faire</h1>
      <div class="section-links">
        <a href="#/etalonnages">Étalonnages</a>
        <a href="#/habilitations">Habilitations</a>
        ${isAdmin() ? '<a href="#/periodicites">Périodicités</a>' : ""}
      </div>
    </div>
    <div class="stat-grid">
      <div class="stat-tile stat-red"><div class="stat-value">${counts.overdue}</div><div class="stat-label">En retard</div></div>
      <div class="stat-tile"><div class="stat-value">${counts.never}</div><div class="stat-label">Jamais contrôlés</div></div>
      <div class="stat-tile"><div class="stat-value">${counts.soon}</div><div class="stat-label">Bientôt à contrôler</div></div>
    </div>
    <div class="filter-bar">
      <select id="f-kind">
        <option value="">Tout le matériel</option>
        ${Object.entries(KIND_LABEL).map(([k, v]) => `<option value="${k}" ${filter.kind === k ? "selected" : ""}>${v}</option>`).join("")}
      </select>
      <select id="f-status">
        <option value="">Tous les états</option>
        ${Object.entries(STATUS).map(([k, [, v]]) => `<option value="${k}" ${filter.status === k ? "selected" : ""}>${v}</option>`).join("")}
      </select>
      <div class="section-links">
        <button class="btn btn-sm" id="reg-xlsx">Registre Excel</button>
        <button class="btn btn-sm" id="reg-pdf">Registre PDF</button>
      </div>
    </div>
    <div class="filter-count">${items.length} élément(s)</div>
    <div id="due-list">${items.length ? items.slice(0, PAGE_SIZE).map(card).join("") : `<div class="empty-state">Aucun contrôle en attente.</div>`}</div>
    ${items.length > PAGE_SIZE ? `<div class="load-more"><button class="btn" id="due-more">Afficher plus (${PAGE_SIZE} sur ${items.length})</button></div>` : ""}
  `;

  let shown = Math.min(PAGE_SIZE, items.length);
  document.getElementById("due-more")?.addEventListener("click", (e) => {
    document.getElementById("due-list").insertAdjacentHTML("beforeend", items.slice(shown, shown + PAGE_SIZE).map(card).join(""));
    shown = Math.min(shown + PAGE_SIZE, items.length);
    if (shown >= items.length) e.target.closest(".load-more").remove();
    else e.target.textContent = `Afficher plus (${shown} sur ${items.length})`;
  });

  document.getElementById("f-kind").addEventListener("change", (e) => {
    filter.kind = e.target.value;
    renderControls(app);
  });
  document.getElementById("f-status").addEventListener("change", (e) => {
    filter.status = e.target.value;
    renderControls(app);
  });
  const registry = (format) => async () => {
    try {
      await api.download(`/inspections/registry?tool_kind=${filter.kind || "agency"}&format=${format}`, `registre.${format}`);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur", "error");
    }
  };
  document.getElementById("reg-xlsx").addEventListener("click", registry("xlsx"));
  document.getElementById("reg-pdf").addEventListener("click", registry("pdf"));

  document.getElementById("due-list").addEventListener("click", (e) => {
    const button = e.target.closest('[data-action="inspect"]');
    if (!button) return;
    const cardEl = button.closest(".card");
    openInspectionForm(cardEl.dataset.kind, Number(cardEl.dataset.id), () => renderControls(app));
  });
}
