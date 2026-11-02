import { api, ApiError } from "../api.js";
import { escapeHtml, formatDateTime, toast } from "../ui.js";

const PAGE_SIZE = 50;

const ACTION_LABELS = {
  login_success: "Connexion",
  login_failed: "Connexion échouée",
  logout: "Déconnexion",
  password_changed: "Mot de passe changé",
  password_reset_requested: "Réinitialisation demandée",
  password_reset_done: "Mot de passe réinitialisé (lien)",
  password_reset_by_manager: "Mot de passe réinitialisé par un responsable",
  password_reset_email_failed: "Email de réinitialisation non envoyé",
  refresh_token_reuse: "Réutilisation de jeton détectée",
  profile_updated: "Profil modifié",
  user_created: "Compte créé",
  user_updated: "Compte modifié",
  user_deleted: "Compte supprimé",
  user_tools_reassigned: "Matériel réaffecté",
  agency_created: "Agence créée",
  agency_updated: "Agence modifiée",
  agency_deleted: "Agence supprimée",
  personal_tool_deleted: "Outil personnel supprimé",
  agency_tool_deleted: "Outil d'agence supprimé",
  epi_deleted: "EPI supprimé",
  settings_updated: "Paramètres modifiés",
  export_agency_tools: "Export Excel du parc",
  export_audit_log: "Export du journal d'audit",
  job_run_manual: "Tâche lancée manuellement",
};

let filters = { action: "", q: "", date_from: "", date_to: "" };

function buildQuery(offset) {
  const params = new URLSearchParams();
  if (filters.action) params.set("action", filters.action);
  if (filters.q) params.set("q", filters.q);
  if (filters.date_from) params.set("date_from", new Date(filters.date_from).toISOString());
  if (filters.date_to) params.set("date_to", new Date(`${filters.date_to}T23:59:59`).toISOString());
  if (offset !== undefined) {
    params.set("limit", PAGE_SIZE);
    params.set("offset", offset);
  }
  return params.toString();
}

function row(entry) {
  const label = ACTION_LABELS[entry.action] || entry.action;
  const object = entry.entity_type ? `${entry.entity_type}${entry.entity_id ? ` #${entry.entity_id}` : ""}` : "-";
  return `
    <div class="card">
      <div class="card-row">
        <div class="card-title">${escapeHtml(label)}</div>
        <div class="card-sub">${escapeHtml(formatDateTime(entry.created_at))}</div>
      </div>
      <div class="card-meta">
        <span>Par : ${escapeHtml(entry.user_name || "-")}</span>
        <span>Objet : ${escapeHtml(object)}</span>
        <span>IP : ${escapeHtml(entry.ip || "-")}</span>
      </div>
      ${entry.details ? `<div class="card-sub audit-details">${escapeHtml(entry.details)}</div>` : ""}
    </div>`;
}

export async function renderAudit(app) {
  app.innerHTML = `
    <div class="section-header">
      <h1>Journal d'audit</h1>
      <div class="section-links"><a href="#/parametres">Paramètres</a><button class="btn btn-sm" id="audit-export">Exporter en CSV</button></div>
    </div>
    <form class="filter-bar" id="audit-filters">
      <select name="action">
        <option value="">Toutes les actions</option>
        ${Object.entries(ACTION_LABELS)
          .map(([k, v]) => `<option value="${k}" ${filters.action === k ? "selected" : ""}>${escapeHtml(v)}</option>`)
          .join("")}
      </select>
      <input type="search" name="q" placeholder="Rechercher dans les détails" value="${escapeHtml(filters.q)}"/>
      <input type="date" name="date_from" value="${escapeHtml(filters.date_from)}" aria-label="Du"/>
      <input type="date" name="date_to" value="${escapeHtml(filters.date_to)}" aria-label="Au"/>
      <button type="submit" class="btn btn-sm btn-primary">Filtrer</button>
    </form>
    <div class="filter-count" id="audit-count"></div>
    <div id="audit-list"></div>
    <div class="load-more"><button class="btn" id="audit-more">Charger plus</button></div>
  `;

  const list = document.getElementById("audit-list");
  const count = document.getElementById("audit-count");
  const moreBtn = document.getElementById("audit-more");
  let loaded = 0;
  let total = 0;

  async function loadPage(reset) {
    if (reset) {
      loaded = 0;
      list.innerHTML = "";
    }
    try {
      const { items, total: t } = await api.getPage(`/audit-log?${buildQuery(loaded)}`);
      total = t;
      list.insertAdjacentHTML("beforeend", items.map(row).join(""));
      loaded += items.length;
      count.textContent = `${loaded} / ${total} événement(s)`;
      moreBtn.classList.toggle("hidden", loaded >= total);
      if (!total) list.innerHTML = `<div class="empty-state">Aucun événement.</div>`;
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur", "error");
    }
  }

  document.getElementById("audit-filters").addEventListener("submit", (e) => {
    e.preventDefault();
    filters = Object.fromEntries(new FormData(e.target).entries());
    loadPage(true);
  });
  moreBtn.addEventListener("click", () => loadPage(false));
  document.getElementById("audit-export").addEventListener("click", async () => {
    try {
      await api.download(`/audit-log/export?${buildQuery()}`, "journal-audit.csv");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur", "error");
    }
  });

  await loadPage(true);
}
