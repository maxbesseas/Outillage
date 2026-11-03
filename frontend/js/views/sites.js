import { api, ApiError } from "../api.js";
import { escapeHtml, formatDate, formatDateTime, toast, openModal, closeModal } from "../ui.js";
import { isManager, isAdmin } from "../state.js";
import { getTeam } from "../usersCache.js";
import { getAgencies } from "../agencies.js";

const fail = (err) => toast(err instanceof ApiError ? err.message : "Erreur", "error");
const LOAN_STATUS = { reserve: "Réservé", en_cours: "En cours", termine: "Rendu", annule: "Annulé", attente_validation: "À valider", refuse: "Refusé" };
const euro = (n) => `${Number(n || 0).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;
let filter = { status: "actif", q: "" };

export async function renderSites(app) {
  const params = new URLSearchParams();
  if (filter.status) params.set("status_filter", filter.status);
  if (filter.q) params.set("q", filter.q);
  const sites = await api.get(`/sites?${params}`);

  app.innerHTML = `
    <div class="section-header"><h1>Chantiers</h1>
      ${isManager() ? '<button class="btn btn-primary btn-sm" id="new-site">Nouveau chantier</button>' : ""}</div>
    <div class="filter-bar">
      <select id="s-status"><option value="actif" ${filter.status === "actif" ? "selected" : ""}>En cours</option><option value="clos" ${filter.status === "clos" ? "selected" : ""}>Clos</option><option value="" ${filter.status === "" ? "selected" : ""}>Tous</option></select>
      <input id="s-q" placeholder="Rechercher" value="${escapeHtml(filter.q)}"/>
    </div>
    ${sites.length ? sites.map((s) => `<div class="card" data-id="${s.id}">
      <div class="card-row"><div class="card-title">${escapeHtml(s.name)}${s.code ? ` <span class="card-sub">${escapeHtml(s.code)}</span>` : ""}</div>
        <span class="badge badge-${s.status === "actif" ? "green" : "gray"}"><span class="dot"></span>${s.status === "actif" ? "En cours" : "Clos"}</span></div>
      <div class="card-sub">${escapeHtml([s.client, s.address].filter(Boolean).join(" · ") || "-")}</div>
      <div class="card-meta"><span>${s.tools_on_site} outil(s) sur place</span>${s.manager_name ? `<span>Resp. : ${escapeHtml(s.manager_name)}</span>` : ""}
        ${s.start_date ? `<span>Début : ${formatDate(s.start_date)}</span>` : ""}${s.end_date ? `<span>Fin : ${formatDate(s.end_date)}</span>` : ""}</div></div>`).join("")
      : '<div class="empty-state">Aucun chantier.</div>'}`;

  document.getElementById("s-status").addEventListener("change", (e) => {
    filter.status = e.target.value;
    renderSites(app);
  });
  document.getElementById("s-q").addEventListener("change", (e) => {
    filter.q = e.target.value;
    renderSites(app);
  });
  document.getElementById("new-site")?.addEventListener("click", () => openSiteForm(null, () => renderSites(app)));
  app.querySelectorAll(".card[data-id]").forEach((c) =>
    c.addEventListener("click", () => openSiteSheet(Number(c.dataset.id), () => renderSites(app)))
  );
}

async function openSiteForm(site, onDone) {
  const team = await getTeam();
  const agencies = isAdmin() && !site ? await getAgencies() : [];
  openModal(
    `<div class="modal-header"><div class="card-title">${site ? "Modifier le chantier" : "Nouveau chantier"}</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    <form id="s-form" class="form-grid">
      ${agencies.length ? `<div class="field"><label>Agence</label><select name="agency_number">${agencies.map((a) => `<option value="${escapeHtml(a.name)}">${escapeHtml(a.name)}</option>`).join("")}</select></div>` : ""}
      <div class="field"><label>Nom</label><input name="name" required value="${escapeHtml(site?.name || "")}"/></div>
      <div class="field-row"><div class="field"><label>Code (6 chiffres)</label><input name="code" inputmode="numeric" placeholder="250214" value="${escapeHtml(site?.code || "")}"/></div>
        <div class="field"><label>Client</label><input name="client" value="${escapeHtml(site?.client || "")}"/></div></div>
      <div class="field"><label>Adresse</label><input name="address" value="${escapeHtml(site?.address || "")}"/></div>
      <div class="field-row"><div class="field"><label>Début</label><input type="date" name="start" value="${site?.start_date ? site.start_date.slice(0, 10) : ""}"/></div>
        <div class="field"><label>Fin prévue</label><input type="date" name="end" value="${site?.end_date ? site.end_date.slice(0, 10) : ""}"/></div></div>
      <div class="field"><label>Responsable de chantier</label><select name="manager"><option value="">—</option>${team.filter((u) => u.is_active).map((u) => `<option value="${u.id}" ${site?.manager_id === u.id ? "selected" : ""}>${escapeHtml(u.full_name)}</option>`).join("")}</select></div>
      <div class="field"><label>Notes</label><textarea name="notes" rows="2">${escapeHtml(site?.notes || "")}</textarea></div>
      <button class="btn btn-primary" type="submit">${site ? "Enregistrer" : "Créer"}</button></form>`,
    {
      onMount: (root) => {
        root.querySelector("#c").addEventListener("click", closeModal);
        root.querySelector("#s-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          const body = {
            name: f.get("name"), code: f.get("code") || null, client: f.get("client") || null, address: f.get("address") || null,
            start_date: f.get("start") ? new Date(f.get("start")).toISOString() : null,
            end_date: f.get("end") ? new Date(f.get("end")).toISOString() : null,
            manager_id: f.get("manager") ? Number(f.get("manager")) : null, notes: f.get("notes") || null,
          };
          if (f.get("agency_number")) body.agency_number = f.get("agency_number");
          try {
            if (site) await api.patch(`/sites/${site.id}`, body);
            else await api.post("/sites", body);
            closeModal();
            onDone();
          } catch (err) {
            fail(err);
          }
        });
      },
    }
  );
}

async function openSiteSheet(id, onDone) {
  let data;
  try {
    data = isManager() ? await api.get(`/sites/${id}/sheet`) : { site: await api.get(`/sites/${id}`) };
  } catch (err) {
    fail(err);
    return;
  }
  const s = data.site;
  openModal(
    `<div class="modal-header"><div class="card-title">${escapeHtml(s.name)}</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    <div class="card-meta"><span class="badge badge-${s.status === "actif" ? "green" : "gray"}">${s.status === "actif" ? "En cours" : "Clos"}</span>
      ${s.client ? `<span>${escapeHtml(s.client)}</span>` : ""}${s.address ? `<span>${escapeHtml(s.address)}</span>` : ""}${s.manager_name ? `<span>Resp. : ${escapeHtml(s.manager_name)}</span>` : ""}</div>
    ${s.notes ? `<p class="card-sub">${escapeHtml(s.notes)}</p>` : ""}
    ${data.cost ? `<div class="stat-grid"><div class="stat-tile"><div class="stat-value">${euro(data.cost.total)}</div><div class="stat-label">Coût d'usage du matériel</div></div>
      <div class="stat-tile"><div class="stat-value">${data.cost.days}</div><div class="stat-label">Jours-outils facturés</div></div></div>` : ""}
    ${data.current_tools ? `<h4>Sur le chantier maintenant (${data.current_tools.length})</h4>${data.current_tools.map((t) => `<div class="card-sub"><a href="#/outil/agency/${t.tool_id}">${escapeHtml(t.tool_name)}</a> — ${escapeHtml(t.borrower_name || "-")}, depuis le ${escapeHtml(formatDateTime(t.since))}</div>`).join("") || '<div class="card-sub">Aucun.</div>'}` : ""}
    ${data.cost && data.cost.lines.length ? `<h4>Coût par outil</h4>${data.cost.lines.map((l) => `<div class="card-sub">${escapeHtml(l.tool_name)} — ${l.days} j × ${euro(l.rate)} = <strong>${euro(l.cost)}</strong></div>`).join("")}` : ""}
    ${data.stock_issued && data.stock_issued.length ? `<h4>Consommables sortis</h4>${data.stock_issued.map((m) => `<div class="card-sub">${escapeHtml(m.item)} × ${m.quantity} ${escapeHtml(m.unit)} — ${formatDate(m.date)}</div>`).join("")}` : ""}
    ${data.loans ? `<h4>Historique des sorties</h4>${data.loans.slice(0, 30).map((l) => `<div class="card-sub">${escapeHtml(l.tool_name)} · ${escapeHtml(l.borrower_name || "-")} · ${escapeHtml(LOAN_STATUS[l.status] || l.status)} · ${formatDate(l.start_datetime)}</div>`).join("") || '<div class="card-sub">Aucune sortie.</div>'}` : ""}
    ${isManager() ? `<div class="card-actions"><button class="btn btn-sm" id="edit">Modifier</button>
      ${s.status === "actif" ? '<button class="btn btn-sm btn-danger" id="close-site">Clore le chantier</button>' : '<button class="btn btn-sm" id="reopen">Rouvrir</button>'}</div>` : ""}`,
    {
      onMount: (root) => {
        root.querySelector("#c").addEventListener("click", closeModal);
        root.querySelector("#edit")?.addEventListener("click", () => openSiteForm(s, onDone));
        const act = (sel, path) =>
          root.querySelector(sel)?.addEventListener("click", async () => {
            try {
              await api.post(`/sites/${id}/${path}`);
              closeModal();
              onDone();
            } catch (err) {
              fail(err);
            }
          });
        act("#close-site", "close");
        act("#reopen", "reopen");
      },
    }
  );
}
