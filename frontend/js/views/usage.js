import { api } from "../api.js";
import { escapeHtml, formatDate } from "../ui.js";

let days = 90;
const euro = (n) => `${Number(n || 0).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €`;

const bar = (pct) => `<div class="bar"><div class="bar-fill" style="width:${Math.max(0, Math.min(100, pct))}%"></div><span>${pct} %</span></div>`;

export async function renderUsage(app) {
  const [u, costs] = await Promise.all([api.get(`/stats/utilization?days=${days}`), api.get("/stats/sites-cost")]);

  app.innerHTML = `
    <div class="section-header"><h1>Utilisation du parc</h1>
      <select id="u-days">${[30, 90, 180, 365].map((d) => `<option value="${d}" ${d === days ? "selected" : ""}>${d} derniers jours</option>`).join("")}</select></div>
    <div class="stat-grid">
      <div class="stat-tile"><div class="stat-value">${u.average_utilization_pct} %</div><div class="stat-label">Utilisation moyenne</div></div>
      <div class="stat-tile"><div class="stat-value">${u.dormant.length}</div><div class="stat-label">Outils dormants (≥ ${u.dormant_days} j sans sortie)</div></div>
      <div class="stat-tile"><div class="stat-value">${u.saturated.length}</div><div class="stat-label">Outils saturés (≥ ${u.saturated_pct} % ou liste d'attente)</div></div>
      <div class="stat-tile"><div class="stat-value">${euro(costs.total)}</div><div class="stat-label">Coût d'usage (tous chantiers)</div></div>
    </div>

    <h3>Par type d'outil</h3>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Type</th><th>Outils</th><th>Sorties</th><th>Utilisation moyenne</th></tr></thead><tbody>
      ${u.by_type.map((t) => `<tr><td>${escapeHtml(t.type)}</td><td>${t.tools}</td><td>${t.loans}</td><td>${bar(t.avg_utilization_pct)}</td></tr>`).join("") || '<tr><td colspan="4">Aucune donnée.</td></tr>'}
    </tbody></table></div>

    <h3>Outils saturés</h3>
    ${u.saturated.length ? u.saturated.slice(0, 15).map((t) => `<div class="card-sub"><a href="#/outil/agency/${t.tool_id}">${escapeHtml(t.name)}</a> — ${t.utilization_pct} % ${t.waitlist ? `· ${t.waitlist} en liste d'attente` : ""}
      <em>(envisager un exemplaire supplémentaire)</em></div>`).join("") : '<div class="card-sub">Aucun.</div>'}

    <h3>Outils dormants</h3>
    ${u.dormant.length ? u.dormant.slice(0, 20).map((t) => `<div class="card-sub"><a href="#/outil/agency/${t.tool_id}">${escapeHtml(t.name)}</a> — dernière sortie : ${t.last_loan_at ? formatDate(t.last_loan_at) : "jamais"}
      <em>(à mutualiser ou céder ?)</em></div>`).join("") : '<div class="card-sub">Aucun.</div>'}

    <h3>Coût par chantier</h3>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Chantier</th><th>Statut</th><th>Jours-outils</th><th>Coût</th></tr></thead><tbody>
      ${costs.sites.map((s) => `<tr><td>${escapeHtml(s.name)}</td><td>${s.status === "actif" ? "En cours" : "Clos"}</td><td>${s.days}</td><td>${euro(s.cost)}</td></tr>`).join("") || '<tr><td colspan="4">Aucun chantier.</td></tr>'}
    </tbody></table></div>
    <p class="card-sub">Le coût d'usage applique le tarif journalier de l'outil, ou le forfait par défaut des paramètres ; il est recalculé au tarif en vigueur.</p>`;

  document.getElementById("u-days").addEventListener("change", (e) => {
    days = Number(e.target.value);
    renderUsage(app);
  });
}
