import { api, ApiError } from "../api.js";
import { escapeHtml, formatDateTime, loanStatusBadge, toast, openModal, closeModal } from "../ui.js";
import { isManager } from "../state.js";
import { openLoanDetailModal, openReturnForm } from "../loanActions.js";
import { getAllUsers } from "../usersCache.js";

let filter = "active";
const ACTIVE = ["reserve", "en_cours", "attente_validation"];
const fail = (err) => toast(err instanceof ApiError ? err.message : "Erreur", "error");

function card(l, toolName, selectable) {
  const overdue = l.status === "en_cours" && new Date(l.end_datetime_planned) < new Date();
  return `
    <div class="card" data-loan-id="${l.id}">
      <div class="card-row">
        <div class="card-title">${selectable ? `<input type="checkbox" data-select="${l.id}" aria-label="Sélectionner pour un retour groupé"/> ` : ""}${escapeHtml(toolName)}</div>
        ${loanStatusBadge(l.status)}
      </div>
      <div class="card-sub">${escapeHtml(l.site || "Sans chantier")} · ${formatDateTime(l.start_datetime)} → ${formatDateTime(l.end_datetime_planned)}</div>
      ${overdue ? '<div class="card-meta"><span class="badge badge-red">En retard</span></div>' : ""}
      ${l.status === "termine" ? `<div class="card-meta"><span>État : ${l.state_before ?? "-"}/5 → ${l.state_after ?? "-"}/5</span></div>` : ""}
      <div class="card-actions">
        ${l.status === "reserve" ? '<button class="btn btn-sm btn-primary" data-action="checkout">Retirer</button>' : ""}
        ${l.status === "en_cours" ? '<button class="btn btn-sm btn-primary" data-action="return">Retour</button>' : ""}
        <button class="btn btn-sm" data-action="detail">Détails</button>
      </div>
    </div>`;
}

export async function drawMine(container) {
  const [loans, tools, waitlist] = await Promise.all([api.get("/loans?scope=mine"), api.get("/agency-tools"), api.get("/waitlist")]);
  await getAllUsers();
  const toolById = Object.fromEntries(tools.map((t) => [t.id, t]));

  let list = loans;
  let pendingForMe = [];
  if (filter === "active") list = loans.filter((l) => ACTIVE.includes(l.status));
  if (isManager()) pendingForMe = await api.get("/loans/pending-approval");
  const outNow = loans.filter((l) => l.status === "en_cours");

  container.innerHTML = `
    <div class="tag-row" id="mine-filters">
      <button data-f="active" class="${filter === "active" ? "active" : ""}">En cours</button>
      <button data-f="all" class="${filter === "all" ? "active" : ""}">Toutes</button>
    </div>
    <div class="card-actions" style="margin-bottom:0.75rem;">
      <button class="btn btn-sm" id="batch-toggle">Retour groupé</button>
      <button class="btn btn-sm hidden" id="batch-go">Rendre la sélection</button>
      <button class="btn btn-sm" id="kit-btn">Réserver un kit</button>
      ${pendingForMe.length ? `<a class="btn btn-sm btn-primary" href="#/planification">${pendingForMe.length} réservation(s) à valider</a>` : ""}
    </div>
    <div id="mine-list">${list.length ? list.map((l) => card(l, toolById[l.tool_id]?.name || "Outil", false)).join("") : `<div class="empty-state">Aucune réservation.</div>`}</div>
    ${
      waitlist.length
        ? `<h3>Ma liste d'attente</h3>${waitlist
            .map(
              (w) => `<div class="card" data-wait="${w.id}"><div class="card-row"><div class="card-title">${escapeHtml(w.tool_name)}</div>
              <span class="badge ${w.status === "offered" ? "badge-green" : "badge-gray"}">${w.status === "offered" ? "Disponible !" : "En attente"}</span></div>
              <div class="card-sub">${formatDateTime(w.start_datetime)} → ${formatDateTime(w.end_datetime)}${w.offer_expires_at ? ` · à confirmer avant ${formatDateTime(w.offer_expires_at)}` : ""}</div>
              <div class="card-actions">${w.status === "offered" ? '<button class="btn btn-sm btn-primary" data-wait-action="accept">Réserver</button>' : ""}
              <button class="btn btn-sm btn-danger" data-wait-action="leave">Quitter la liste</button></div></div>`
            )
            .join("")}`
        : ""
    }
  `;

  const refresh = () => drawMine(container);

  container.querySelectorAll("#mine-filters button").forEach((btn) =>
    btn.addEventListener("click", () => {
      filter = btn.dataset.f;
      refresh();
    })
  );

  container.querySelectorAll("[data-loan-id]").forEach((el) => {
    const loan = loans.find((l) => l.id === Number(el.dataset.loanId));
    const tool = toolById[loan.tool_id];
    el.querySelector('[data-action="detail"]').addEventListener("click", () => openLoanDetailModal(loan, tool, refresh));
    el.querySelector('[data-action="return"]')?.addEventListener("click", () => openReturnForm(loan, refresh));
    el.querySelector('[data-action="checkout"]')?.addEventListener("click", async () => {
      try {
        await api.post(`/loans/${loan.id}/checkout`, {});
        toast("Outil retiré", "success");
        refresh();
      } catch (err) {
        fail(err);
      }
    });
  });

  container.querySelectorAll("[data-wait]").forEach((el) => {
    const id = Number(el.dataset.wait);
    el.querySelector('[data-wait-action="accept"]')?.addEventListener("click", async () => {
      try {
        await api.post(`/waitlist/${id}/accept`);
        toast("Réservation créée", "success");
        refresh();
      } catch (err) {
        fail(err);
        refresh();
      }
    });
    el.querySelector('[data-wait-action="leave"]').addEventListener("click", async () => {
      await api.delete(`/waitlist/${id}`);
      refresh();
    });
  });

  // retour groupé
  let batchMode = false;
  const toggle = container.querySelector("#batch-toggle");
  const go = container.querySelector("#batch-go");
  toggle.addEventListener("click", () => {
    batchMode = !batchMode;
    go.classList.toggle("hidden", !batchMode);
    toggle.textContent = batchMode ? "Annuler" : "Retour groupé";
    container.querySelectorAll("[data-loan-id]").forEach((el) => {
      const loan = loans.find((l) => l.id === Number(el.dataset.loanId));
      const title = el.querySelector(".card-title");
      const existing = title.querySelector("[data-select]");
      if (existing) existing.remove();
      if (batchMode && loan.status === "en_cours") title.insertAdjacentHTML("afterbegin", `<input type="checkbox" data-select="${loan.id}" aria-label="Sélectionner"/> `);
    });
    if (batchMode && !outNow.length) toast("Aucun outil en cours à rendre", "error");
  });
  go.addEventListener("click", () => {
    const ids = [...container.querySelectorAll("[data-select]:checked")].map((c) => Number(c.dataset.select));
    if (!ids.length) {
      toast("Sélectionnez au moins une réservation", "error");
      return;
    }
    openBatchReturn(ids.map((id) => loans.find((l) => l.id === id)), toolById, refresh);
  });

  container.querySelector("#kit-btn").addEventListener("click", () => openKitReserve(refresh));
}

function openBatchReturn(selected, toolById, onDone) {
  openModal(
    `<div class="modal-header"><div class="card-title">Retour groupé (${selected.length})</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    <form id="batch-form" class="form-grid">
      ${selected
        .map(
          (l) => `<div class="card" data-id="${l.id}"><div class="card-title">${escapeHtml(toolById[l.tool_id]?.name || "Outil")}</div>
          <div class="field-row"><div class="field"><label>État (0-5)</label><input type="number" name="state" min="0" max="5" value="${l.state_before ?? 5}" required/></div>
          <div class="field"><label>Commentaire</label><input name="comment"/></div></div></div>`
        )
        .join("")}
      <button type="submit" class="btn btn-primary">Rendre les ${selected.length} outil(s)</button>
    </form>`,
    {
      onMount: (root) => {
        root.querySelector("#c").addEventListener("click", closeModal);
        root.querySelector("#batch-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const returns = [...root.querySelectorAll("[data-id]")].map((row) => ({
            loan_id: Number(row.dataset.id),
            state_after: Number(row.querySelector('[name="state"]').value),
            comment_return: row.querySelector('[name="comment"]').value || null,
          }));
          try {
            const res = await api.post("/loans/batch-return", { returns });
            toast(`${res.done} retour(s) enregistré(s)${res.failed ? `, ${res.failed} en échec : ${res.results.filter((r) => !r.ok).map((r) => r.detail).join(" ; ")}` : ""}`, res.failed ? "error" : "success");
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

async function openKitReserve(onDone) {
  const kits = await api.get("/kits");
  if (!kits.length) {
    toast("Aucun kit n'est défini pour votre agence (Planification → Kits)", "error");
    return;
  }
  const now = new Date();
  now.setMinutes(0, 0, 0);
  const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  openModal(
    `<div class="modal-header"><div class="card-title">Réserver un kit</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    <form id="kit-form" class="form-grid">
      <div class="field"><label>Kit</label><select name="kit">${kits.map((k) => `<option value="${k.id}">${escapeHtml(k.name)} (${k.tools.length} outils)</option>`).join("")}</select></div>
      <div class="field"><label>Début</label><input type="datetime-local" name="start" value="${iso(now)}" required/></div>
      <div class="field"><label>Fin</label><input type="datetime-local" name="end" value="${iso(new Date(now.getTime() + 8 * 3600 * 1000))}" required/></div>
      <div class="field"><label>Chantier</label><input name="site"/></div>
      <button type="submit" class="btn btn-primary">Réserver tout le kit</button>
    </form>`,
    {
      onMount: (root) => {
        root.querySelector("#c").addEventListener("click", closeModal);
        root.querySelector("#kit-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          try {
            const res = await api.post(`/kits/${f.get("kit")}/reserve`, {
              start_datetime: new Date(f.get("start")).toISOString(),
              end_datetime_planned: new Date(f.get("end")).toISOString(),
              site: f.get("site") || null,
            });
            toast(`${res.count} outil(s) réservé(s)`, "success");
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
