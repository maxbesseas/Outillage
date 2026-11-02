import { api } from "../api.js";
import { escapeHtml, formatDateTime, loanStatusBadge, stateReasonBadge } from "../ui.js";
import { isAdmin, isManager, state } from "../state.js";
import { toast } from "../ui.js";

const KIND_LABEL = { personal: "Outil perso", agency: "Outil agence", epi: "EPI" };

export async function renderDashboard(app) {
  const [overdue, personalTools, agencyTools, due, loans, transfers] = await Promise.all([
    api.get("/dashboard/overdue"),
    api.get("/personal-tools"),
    api.get("/agency-tools"),
    api.get("/inspections/due"),
    api.get("/loans?scope=team"),
    api.get("/transfers?scope=team"),
  ]);

  const activeLoans = loans.filter((l) => l.status === "reserve" || l.status === "en_cours");
  const activeTransfers = transfers.filter((t) => t.status === "en_cours");

  const overdueItems = due.items
    .filter((i) => i.status !== "soon")
    .map((i) => ({ name: i.name, kind: KIND_LABEL[i.kind] || i.kind, link: `#/outil/${i.kind}/${i.id}` }));

  const flaggedTools = personalTools.filter((t) => t.state_reason !== "normal").slice(0, 5);

  app.innerHTML = `
    <div class="section-header"><h1>Tableau de bord</h1></div>

    ${overdueBlock(overdue)}

    <div class="stat-grid">
      <div class="stat-tile">
        <div class="stat-value">${personalTools.length}</div>
        <div class="stat-label">Mes outils personnels</div>
      </div>
      <div class="stat-tile">
        <div class="stat-value">${agencyTools.length}</div>
        <div class="stat-label">${isAdmin() ? "Outils toutes agences" : "Outils d'agence"}</div>
      </div>
      <div class="stat-tile">
        <div class="stat-value">${activeLoans.length}</div>
        <div class="stat-label">Réservations actives</div>
      </div>
      <div class="stat-tile">
        <div class="stat-value">${activeTransfers.length}</div>
        <div class="stat-label">Prêts externes actifs</div>
      </div>
    </div>

    ${
      overdueItems.length
        ? `
      <div class="alert-block warning">
        <strong>À contrôler (${overdueItems.length})</strong> <a href="#/controles">Tout voir</a>
        <div class="card-meta" style="margin-top:0.5rem;">
          ${overdueItems
            .slice(0, 8)
            .map((it) => `<a class="badge badge-orange" href="${it.link}">${escapeHtml(it.kind)} · ${escapeHtml(it.name)}</a>`)
            .join("")}
          ${overdueItems.length > 8 ? `<span>+${overdueItems.length - 8} autres</span>` : ""}
        </div>
      </div>`
        : ""
    }

    ${
      flaggedTools.length
        ? `
      <h3>Outils à signaler / suivre</h3>
      ${flaggedTools
        .map(
          (t) => `
        <div class="card">
          <div class="card-row">
            <div class="card-title">${escapeHtml(t.name)}</div>
            ${stateReasonBadge(t.state_reason)}
          </div>
        </div>`
        )
        .join("")}`
        : ""
    }

    <h3>Réservations récentes</h3>
    ${
      activeLoans.length
        ? activeLoans
            .slice(0, 5)
            .map(
              (l) => `
        <div class="card">
          <div class="card-row">
            <div class="card-title">${escapeHtml(l.site || "Sans chantier")}</div>
            ${loanStatusBadge(l.status)}
          </div>
          <div class="card-sub">${formatDateTime(l.start_datetime)} → ${formatDateTime(l.end_datetime_planned)}</div>
        </div>`
            )
            .join("")
        : `<div class="empty-state">Aucune réservation active.</div>`
    }
  `;
}


function overdueBlock(overdue) {
  const total = overdue.loans.length + overdue.transfers.length;
  const toConfirm = overdue.peer_transfers.filter((p) => p.needs_my_confirmation).length;
  const confirmLine = toConfirm
    ? `<div class="card-row overdue-row"><span>${toConfirm} transfert(s) entre collègues à confirmer</span><a class="btn btn-sm" href="#/entre-collegues">Voir</a></div>`
    : "";

  if (!total && !toConfirm) {
    return `<div class="alert-block ok-block"><strong>Rien en retard</strong><div class="card-sub">Toutes les réservations et tous les prêts sont à jour.</div></div>`;
  }

  const loanRows = overdue.loans
    .map((l) => {
      const mine = l.borrower_id === state.user.id;
      return `<div class="card-row overdue-row">
        <span><strong>${escapeHtml(l.tool_name)}</strong> — ${escapeHtml(mine ? "vous" : l.borrower_name)}, ${l.days_late} jour(s) de retard</span>
        ${mine ? '<a class="btn btn-sm btn-primary" href="#/reservations">Rendre</a>' : isManager() ? `<button class="btn btn-sm" data-remind="${l.id}">Relancer</button>` : ""}
      </div>`;
    })
    .join("");
  const transferRows = overdue.transfers
    .map(
      (t) => `<div class="card-row overdue-row">
        <span><strong>${escapeHtml(t.tool_name)}</strong> prêté à ${escapeHtml(t.recipient)} (${escapeHtml(t.from_name)}), ${t.days_late} jour(s) de retard</span>
        <a class="btn btn-sm" href="#/transferts">Voir</a>
      </div>`
    )
    .join("");

  return `<div class="alert-block" id="overdue-block"><strong>En retard (${total})</strong>${loanRows}${transferRows}${confirmLine}</div>`;
}

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-remind]");
  if (!btn) return;
  btn.disabled = true;
  try {
    await api.post(`/loans/${btn.dataset.remind}/remind`);
    toast("Rappel envoyé", "success");
  } catch (err) {
    toast(err.message || "Erreur", "error");
    btn.disabled = false;
  }
});
