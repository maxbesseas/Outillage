import { api, ApiError } from "../api.js";
import { escapeHtml, formatDate, toast, openModal, closeModal } from "../ui.js";
import { isAdmin, state } from "../state.js";
import { getTeam } from "../usersCache.js";

const fail = (err) => toast(err instanceof ApiError ? err.message : "Erreur", "error");
const euro = (n) => (n === null || n === undefined ? "-" : `${Number(n).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`);
const KIND = { vol: "Vol", perte: "Perte", casse: "Casse", litige: "Litige" };
const INSURANCE = { none: "Aucune", declared: "Déclarée", accepted: "Acceptée", refused: "Refusée" };
const LITIGATION = { none: "Aucun", open: "En cours", closed: "Clos" };
const CATEGORY = { achats: "Achats d'outillage", reparations: "Réparations", pertes: "Pertes nettes" };
const DATASETS = {
  workbook: "Classeur complet (toutes les feuilles)", tools: "Outils", epi: "EPI", assets: "Actifs et amortissement", tco: "Coût total de possession",
  loans: "Réservations", tickets: "Maintenance", losses: "Pertes et litiges", "sites-cost": "Coûts par chantier", stock: "Stock", budgets: "Budgets",
};

export function tabs(active) {
  const items = [["/finances", "Vue d'ensemble"], ["/finances/actifs", "Actifs"], ["/finances/pertes", "Pertes"], ["/finances/budgets", "Budgets"], ["/exports", "Exports"]];
  return `<div class="tag-row">${items.map(([p, l]) => `<a class="tag ${p === active ? "active" : ""}" href="#${p}">${l}</a>`).join("")}</div>`;
}

export async function renderAssets(app) {
  const [assets, tco, forecast, pol] = await Promise.all([
    api.get("/finance/assets"), api.get("/finance/tco?limit=15"), api.get("/finance/forecast?months=12"), api.get("/finance/depreciation-policies"),
  ]);
  const t = assets.totals;
  app.innerHTML = `
    <div class="section-header"><h1>Actifs et amortissement</h1></div>${tabs("/finances/actifs")}
    <div class="stat-grid">
      <div class="stat-tile"><div class="stat-value">${euro(t.book_value)}</div><div class="stat-label">Valeur nette comptable</div></div>
      <div class="stat-tile"><div class="stat-value">${euro(t.acquisition)}</div><div class="stat-label">Valeur d'acquisition</div></div>
      <div class="stat-tile"><div class="stat-value">${t.fully_depreciated}</div><div class="stat-label">Outils totalement amortis</div></div>
      <div class="stat-tile"><div class="stat-value">${t.incomplete}</div><div class="stat-label">Sans prix ou date d'achat</div></div>
    </div>
    <p class="card-sub">Amortissement linéaire. Règle par défaut : ${pol.defaults.years} an(s), résiduel ${pol.defaults.residual_pct} % (à valider par la comptabilité).</p>
    ${isAdmin() ? `<form id="pol-form" class="filter-bar"><input name="type" placeholder="Type (vide = règle par défaut)"/><input name="years" type="number" step="0.5" min="0.5" placeholder="Années" required/>
      <input name="residual" type="number" min="0" max="100" placeholder="Résiduel %" value="0"/><button class="btn btn-sm">Enregistrer la règle</button></form>` : ""}
    ${pol.policies.length ? `<div class="card-sub">Règles : ${pol.policies.map((p) => `${escapeHtml(p.type || "défaut")} : ${p.years} an(s) / ${p.residual_pct} %${isAdmin() ? ` <button class="btn btn-sm" data-del-pol="${p.id}">Retirer</button>` : ""}`).join(" · ")}</div>` : ""}

    <h3>Par type</h3>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Type</th><th>Outils</th><th>Acquisition</th><th>Valeur nette</th></tr></thead><tbody>
      ${assets.by_type.map((a) => `<tr><td>${escapeHtml(a.type)}</td><td>${a.count}</td><td>${euro(a.acquisition)}</td><td>${euro(a.book_value)}</td></tr>`).join("") || '<tr><td colspan="4">Aucun actif complet.</td></tr>'}
    </tbody></table></div>

    <h3>Renouvellement à prévoir (12 mois)</h3>
    <p class="card-sub">${forecast.replacements.length} outil(s) en fin d'amortissement, budget estimé ${euro(forecast.replacements_total)} · ${forecast.epi_total} EPI à renouveler.</p>
    ${forecast.replacements.slice(0, 10).map((r) => `<div class="card-sub"><a href="#/outil/agency/${r.tool_id}">${escapeHtml(r.name)}</a> — ${r.overdue ? "amorti depuis" : "fin le"} ${formatDate(r.end_of_life)} · ${euro(r.estimated_cost)}</div>`).join("")}
    ${forecast.epi_to_renew.length ? `<div class="card-sub">EPI : ${forecast.epi_to_renew.map((e) => `${escapeHtml(e.type)} (${e.count})`).join(", ")}</div>` : ""}

    <h3>Coût total de possession — 15 plus élevés</h3>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Outil</th><th>Achat</th><th>Réparations</th><th>TCO</th><th>€ / jour d'usage</th></tr></thead><tbody>
      ${tco.tools.map((x) => `<tr><td><a href="#/outil/agency/${x.tool_id}">${escapeHtml(x.name)}</a></td><td>${euro(x.purchase_price)}</td><td>${euro(x.repair_cost)}</td><td>${euro(x.tco)}</td><td>${euro(x.cost_per_day_used)}</td></tr>`).join("")}
    </tbody></table></div>`;

  document.getElementById("pol-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api.put("/finance/depreciation-policies", { type: f.get("type") || null, years: Number(f.get("years")), residual_pct: Number(f.get("residual") || 0) });
      renderAssets(app);
    } catch (err) {
      fail(err);
    }
  });
  app.querySelectorAll("[data-del-pol]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await api.delete(`/finance/depreciation-policies/${b.dataset.delPol}`);
        renderAssets(app);
      } catch (err) {
        fail(err);
      }
    })
  );
}

export async function renderLosses(app) {
  const data = await api.get("/losses");
  const t = data.totals;
  app.innerHTML = `
    <div class="section-header"><h1>Pertes et litiges</h1><button class="btn btn-primary btn-sm" id="new-loss">Déclarer une perte</button></div>${tabs("/finances/pertes")}
    <div class="stat-grid">
      <div class="stat-tile"><div class="stat-value">${t.count}</div><div class="stat-label">Dossiers</div></div>
      <div class="stat-tile"><div class="stat-value">${euro(t.declared)}</div><div class="stat-label">Valeur déclarée</div></div>
      <div class="stat-tile"><div class="stat-value">${euro(t.refunded)}</div><div class="stat-label">Remboursé</div></div>
      <div class="stat-tile"><div class="stat-value">${euro(t.net)}</div><div class="stat-label">Perte nette (${t.open_litigations} litige(s) en cours)</div></div>
    </div>
    ${data.records.map((l) => `<div class="card" data-id="${l.id}"><div class="card-row"><div class="card-title">${escapeHtml(l.tool_name)} <span class="card-sub">${escapeHtml(l.tool_code || "")}</span></div>
      <span class="badge badge-red">${escapeHtml(KIND[l.kind] || l.kind)}</span></div>
      <div class="card-sub">${formatDate(l.occurred_at)}${l.responsible_name ? ` · ${escapeHtml(l.responsible_name)}` : ""}${l.circumstances ? ` — ${escapeHtml(l.circumstances)}` : ""}</div>
      <div class="card-meta"><span>Déclaré : ${euro(l.declared_value)}</span><span>Remboursé : ${euro(l.refunded_amount)}</span><span>Net : <strong>${euro(l.net_loss)}</strong></span>
        <span>Assurance : ${INSURANCE[l.insurance_status]}${l.insurance_ref ? ` (${escapeHtml(l.insurance_ref)})` : ""}</span>
        ${l.police_report_ref ? `<span>Plainte : ${escapeHtml(l.police_report_ref)}</span>` : ""}<span>Litige : ${LITIGATION[l.litigation_status]}</span></div></div>`).join("") || '<div class="empty-state">Aucun dossier.</div>'}`;

  document.getElementById("new-loss").addEventListener("click", () => openLossForm(null, () => renderLosses(app)));
  app.querySelectorAll(".card[data-id]").forEach((c) =>
    c.addEventListener("click", () => openLossForm(data.records.find((r) => r.id === Number(c.dataset.id)), () => renderLosses(app)))
  );
}

async function openLossForm(loss, onDone) {
  const team = await getTeam();
  const tools = loss ? [] : await api.get("/agency-tools");
  const opt = (map, cur) => Object.entries(map).map(([k, v]) => `<option value="${k}" ${k === cur ? "selected" : ""}>${v}</option>`).join("");
  openModal(
    `<div class="modal-header"><div class="card-title">${loss ? `Dossier — ${escapeHtml(loss.tool_name)}` : "Déclarer une perte"}</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    <form id="l-form" class="form-grid">
      ${loss ? "" : `<div class="field"><label>Outil</label><select name="tool_id" required>${tools.filter((t) => t.status !== "sorti_du_parc").map((t) => `<option value="${t.id}">${escapeHtml(t.name)} (${escapeHtml(t.unique_code)})</option>`).join("")}</select></div>
      <div class="field"><label>Nature</label><select name="kind">${opt(KIND, "vol")}</select></div>`}
      <div class="field"><label>Responsable</label><select name="responsible_id"><option value="">—</option>${team.map((u) => `<option value="${u.id}" ${loss?.responsible_id === u.id ? "selected" : ""}>${escapeHtml(u.full_name)}</option>`).join("")}</select></div>
      <div class="field"><label>Circonstances</label><textarea name="circumstances" rows="2">${escapeHtml(loss?.circumstances || "")}</textarea></div>
      <div class="field-row"><div class="field"><label>Valeur déclarée (€, vide = prix d'achat)</label><input type="number" step="0.01" min="0" name="declared_value" value="${loss?.declared_value ?? ""}"/></div>
        <div class="field"><label>Remboursé (€)</label><input type="number" step="0.01" min="0" name="refunded_amount" value="${loss?.refunded_amount ?? 0}"/></div></div>
      <div class="field-row"><div class="field"><label>Assurance</label><select name="insurance_status">${opt(INSURANCE, loss?.insurance_status || "none")}</select></div>
        <div class="field"><label>Réf. sinistre</label><input name="insurance_ref" value="${escapeHtml(loss?.insurance_ref || "")}"/></div></div>
      <div class="field"><label>Réf. dépôt de plainte</label><input name="police_report_ref" value="${escapeHtml(loss?.police_report_ref || "")}"/></div>
      <div class="field-row"><div class="field"><label>Litige</label><select name="litigation_status">${opt(LITIGATION, loss?.litigation_status || "none")}</select></div>
        <div class="field"><label>Note de litige</label><input name="litigation_note" value="${escapeHtml(loss?.litigation_note || "")}"/></div></div>
      <button class="btn btn-primary" type="submit">Enregistrer</button></form>`,
    {
      onMount: (root) => {
        root.querySelector("#c").addEventListener("click", closeModal);
        root.querySelector("#l-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          const body = {
            responsible_id: f.get("responsible_id") ? Number(f.get("responsible_id")) : null, circumstances: f.get("circumstances") || null,
            declared_value: f.get("declared_value") !== "" ? Number(f.get("declared_value")) : null, refunded_amount: Number(f.get("refunded_amount") || 0),
            insurance_status: f.get("insurance_status"), insurance_ref: f.get("insurance_ref") || null, police_report_ref: f.get("police_report_ref") || null,
            litigation_status: f.get("litigation_status"), litigation_note: f.get("litigation_note") || null,
          };
          try {
            if (loss) await api.patch(`/losses/${loss.id}`, body);
            else await api.post("/losses", { ...body, tool_id: Number(f.get("tool_id")), kind: f.get("kind") });
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

let budgetYear = new Date().getFullYear();

export async function renderBudgets(app) {
  const b = await api.get(`/finance/budgets?year=${budgetYear}`);
  const canEdit = state.user.role === "admin" || state.user.role === "directeur_agence";
  app.innerHTML = `
    <div class="section-header"><h1>Budgets</h1><select id="b-year">${[-1, 0, 1].map((d) => `<option ${budgetYear === new Date().getFullYear() + d ? "selected" : ""}>${new Date().getFullYear() + d}</option>`).join("")}</select></div>${tabs("/finances/budgets")}
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Poste</th><th>Budget</th><th>Réalisé</th><th>Reste</th><th>Consommé</th></tr></thead><tbody>
      ${b.rows.map((r) => `<tr><td>${CATEGORY[r.category]}</td><td>${canEdit ? `<input class="inline-num" type="number" min="0" step="10" data-cat="${r.category}" value="${r.planned}"/>` : euro(r.planned)}</td>
        <td>${euro(r.actual)}</td><td class="${r.remaining < 0 ? "neg" : ""}">${euro(r.remaining)}</td><td>${r.consumed_pct === null ? "-" : `${r.consumed_pct} %`}</td></tr>`).join("")}
      <tr><th>Total</th><th>${euro(b.planned_total)}</th><th>${euro(b.actual_total)}</th><th></th><th></th></tr>
    </tbody></table></div>
    ${canEdit ? '<p class="card-sub">Modifiez un montant puis quittez le champ pour l\'enregistrer.</p>' : '<p class="card-sub">Les budgets sont fixés par le directeur d\'agence.</p>'}`;

  document.getElementById("b-year").addEventListener("change", (e) => {
    budgetYear = Number(e.target.value);
    renderBudgets(app);
  });
  app.querySelectorAll("[data-cat]").forEach((input) =>
    input.addEventListener("change", async () => {
      try {
        await api.put("/finance/budgets", { year: budgetYear, category: input.dataset.cat, amount: Number(input.value || 0) });
        renderBudgets(app);
      } catch (err) {
        fail(err);
      }
    })
  );
}

export async function renderExports(app) {
  const keys = isAdmin() ? await api.get("/api-keys") : [];
  app.innerHTML = `
    <div class="section-header"><h1>Exports</h1></div>${tabs("/exports")}
    <p class="card-sub">Fichiers CSV (UTF-8, séparateur « ; », ouverture directe dans Excel) ou Excel. Les exports sont limités à votre agence et journalisés.</p>
    <div class="table-wrap"><table class="data-table"><tbody>
      ${Object.entries(DATASETS).map(([k, label]) => `<tr><td>${label}</td><td>${k === "workbook" ? "" : `<button class="btn btn-sm" data-ds="${k}" data-fmt="csv">CSV</button> `}<button class="btn btn-sm" data-ds="${k}" data-fmt="xlsx">Excel</button></td></tr>`).join("")}
    </tbody></table></div>
    ${isAdmin() ? `<h3>Clés d'accès API (lecture seule)</h3>
      <p class="card-sub">Pour brancher un outil de reporting : <code>GET /reports/{jeu}</code> avec l'en-tête <code>X-API-Key</code>. 60 requêtes par minute et par clé.</p>
      <form id="k-form" class="filter-bar"><input name="name" placeholder="Nom de la clé" required/><input name="agency" placeholder="Agence (vide = toutes)"/><input name="days" type="number" min="1" placeholder="Validité (jours)"/><button class="btn btn-sm">Créer une clé</button></form>
      ${keys.map((k) => `<div class="card"><div class="card-row"><div class="card-title">${escapeHtml(k.name)} <span class="card-sub">${escapeHtml(k.prefix)}…</span></div>
        <span class="badge badge-${k.is_active ? "green" : "gray"}">${k.is_active ? "Active" : "Révoquée"}</span></div>
        <div class="card-sub">${k.agency_number ? `Agence ${escapeHtml(k.agency_number)}` : "Toutes agences"} · créée le ${formatDate(k.created_at)}${k.last_used_at ? ` · utilisée le ${formatDate(k.last_used_at)}` : " · jamais utilisée"}${k.expires_at ? ` · expire le ${formatDate(k.expires_at)}` : ""}</div>
        ${k.is_active ? `<div class="card-actions"><button class="btn btn-sm btn-danger" data-revoke="${k.id}">Révoquer</button></div>` : ""}</div>`).join("")}` : ""}`;

  app.querySelectorAll("[data-ds]").forEach((b) =>
    b.addEventListener("click", async () => {
      const ds = b.dataset.ds;
      try {
        if (ds === "workbook") await api.download("/exports/workbook", "fauche-export.xlsx");
        else await api.download(`/exports/${ds}?format=${b.dataset.fmt}`, `fauche-${ds}.${b.dataset.fmt}`);
      } catch (err) {
        fail(err);
      }
    })
  );
  document.getElementById("k-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const res = await api.post("/api-keys", { name: f.get("name"), agency_number: f.get("agency") || null, expires_days: f.get("days") ? Number(f.get("days")) : null });
      openModal(
        `<div class="modal-header"><div class="card-title">Clé créée</div></div>
        <p class="card-sub">${escapeHtml(res.warning)}</p><input readonly id="secret" value="${escapeHtml(res.key)}" style="width:100%"/>
        <div class="card-actions"><button class="btn btn-primary" id="done">J'ai copié la clé</button></div>`,
        {
          onMount: (root) => {
            root.querySelector("#secret").select();
            root.querySelector("#done").addEventListener("click", () => {
              closeModal();
              renderExports(app);
            });
          },
        }
      );
    } catch (err) {
      fail(err);
    }
  });
  app.querySelectorAll("[data-revoke]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await api.delete(`/api-keys/${b.dataset.revoke}`);
        renderExports(app);
      } catch (err) {
        fail(err);
      }
    })
  );
}
