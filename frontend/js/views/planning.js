import { api, ApiError } from "../api.js";
import { escapeHtml, formatDateTime, formatDate, toast, openModal, closeModal, toDatetimeLocal, confirmDialog, promptDialog } from "../ui.js";
import { isAdmin, isManager, state } from "../state.js";
import { getAgencies } from "../agencies.js";
import { openLoanDetailModal } from "../loanActions.js";

const TABS = [
  ["validations", "Validations"],
  ["kits", "Kits"],
  ["indispos", "Indisponibilités"],
  ["regles", "Règles"],
  ["agences", "Entre agences"],
];
const REASONS = { maintenance: "Maintenance", etalonnage: "Étalonnage", controle: "Contrôle", autre: "Autre" };
const fail = (err) => toast(err instanceof ApiError ? err.message : "Erreur", "error");
let tab = "validations";

export async function renderPlanning(app) {
  app.innerHTML = `
    <div class="section-header"><h1>Planification</h1></div>
    <div class="tag-row" id="plan-tabs">${TABS.map(([k, l]) => `<button data-tab="${k}" class="${tab === k ? "active" : ""}">${l}</button>`).join("")}</div>
    <div id="plan-body"></div>`;
  document.querySelectorAll("#plan-tabs button").forEach((b) =>
    b.addEventListener("click", () => {
      tab = b.dataset.tab;
      renderPlanning(app);
    })
  );
  const body = document.getElementById("plan-body");
  const draw = { validations, kits, indispos, regles, agences }[tab];
  await draw(body, () => renderPlanning(app));
}

async function validations(body, refresh) {
  const pending = await api.get("/loans/pending-approval");
  body.innerHTML = pending.length
    ? pending
        .map(
          (l) => `<div class="card" data-id="${l.id}"><div class="card-row"><div class="card-title">${escapeHtml(l.tool_name)}</div>
          <span class="badge badge-orange">À valider</span></div>
          <div class="card-sub">${escapeHtml(l.borrower_name)} · ${formatDateTime(l.start_datetime)} → ${formatDateTime(l.end_datetime_planned)}${l.site ? ` · ${escapeHtml(l.site)}` : ""}</div>
          <div class="card-actions"><button class="btn btn-sm btn-primary" data-open>Examiner</button></div></div>`
        )
        .join("")
    : `<div class="empty-state">Aucune réservation en attente de validation.</div>`;
  body.querySelectorAll("[data-id]").forEach((el) => {
    const loan = pending.find((l) => l.id === Number(el.dataset.id));
    el.querySelector("[data-open]").addEventListener("click", () => openLoanDetailModal(loan, { name: loan.tool_name }, refresh));
  });
}

async function kits(body, refresh) {
  const [list, tools] = await Promise.all([api.get("/kits"), api.get("/agency-tools")]);
  body.innerHTML = `
    ${isManager() ? '<div class="card-actions"><button class="btn btn-sm btn-primary" id="kit-new">Nouveau kit</button></div>' : ""}
    ${list.length
      ? list.map((k) => `<div class="card" data-id="${k.id}"><div class="card-row"><div class="card-title">${escapeHtml(k.name)}</div>
        ${isManager() ? '<button class="btn btn-sm btn-danger" data-del>Supprimer</button>' : ""}</div>
        <div class="card-sub">${k.tools.map((t) => escapeHtml(t.name)).join(" · ")}</div>
        ${k.description ? `<div class="card-sub">${escapeHtml(k.description)}</div>` : ""}</div>`).join("")
      : `<div class="empty-state">Aucun kit. Un kit regroupe des outils réservés ensemble.</div>`}`;
  body.querySelector("#kit-new")?.addEventListener("click", () =>
    openModal(
      `<div class="modal-header"><div class="card-title">Nouveau kit</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
      <form id="kit-form" class="form-grid">
        <div class="field"><label>Nom</label><input name="name" required/></div>
        <div class="field"><label>Description</label><input name="description"/></div>
        <div class="field"><label>Outils (Ctrl/Cmd pour en choisir plusieurs)</label>
          <select name="tools" multiple size="8">${tools.map((t) => `<option value="${t.id}">${escapeHtml(t.name)} (${escapeHtml(t.unique_code)})</option>`).join("")}</select></div>
        <button class="btn btn-primary" type="submit">Créer</button></form>`,
      {
        onMount: (root) => {
          root.querySelector("#c").addEventListener("click", closeModal);
          root.querySelector("#kit-form").addEventListener("submit", async (e) => {
            e.preventDefault();
            const f = new FormData(e.target);
            try {
              await api.post("/kits", { name: f.get("name"), description: f.get("description") || null, tool_ids: f.getAll("tools").map(Number) });
              closeModal();
              refresh();
            } catch (err) {
              fail(err);
            }
          });
        },
      }
    )
  );
  body.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!(await confirmDialog("Supprimer ce kit ?", { danger: true }))) return;
      await api.delete(`/kits/${b.closest(".card").dataset.id}`);
      refresh();
    })
  );
}

async function indispos(body, refresh) {
  const [blackouts, tools] = await Promise.all([api.get("/blackouts"), api.get("/agency-tools")]);
  const names = Object.fromEntries(tools.map((t) => [t.id, t.name]));
  body.innerHTML = `
    ${isManager() ? '<div class="card-actions"><button class="btn btn-sm btn-primary" id="bo-new">Déclarer une indisponibilité</button></div>' : ""}
    ${blackouts.length
      ? blackouts.map((b) => `<div class="card" data-id="${b.id}"><div class="card-row"><div class="card-title">${escapeHtml(names[b.tool_id] || "Outil")}</div>
        <span class="badge badge-gray">${REASONS[b.reason] || b.reason}${b.source === "auto" ? " (auto)" : ""}</span></div>
        <div class="card-sub">${formatDateTime(b.start_datetime)} → ${formatDateTime(b.end_datetime)}${b.note ? ` · ${escapeHtml(b.note)}` : ""}</div>
        ${isManager() ? '<div class="card-actions"><button class="btn btn-sm btn-danger" data-del>Supprimer</button></div>' : ""}</div>`).join("")
      : `<div class="empty-state">Aucune indisponibilité déclarée.</div>`}`;
  body.querySelector("#bo-new")?.addEventListener("click", () =>
    openModal(
      `<div class="modal-header"><div class="card-title">Indisponibilité</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
      <form id="bo-form" class="form-grid">
        <div class="field"><label>Outil</label><select name="tool">${tools.map((t) => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join("")}</select></div>
        <div class="field"><label>Début</label><input type="datetime-local" name="start" value="${toDatetimeLocal(new Date())}" required/></div>
        <div class="field"><label>Fin</label><input type="datetime-local" name="end" required/></div>
        <div class="field"><label>Motif</label><select name="reason">${Object.entries(REASONS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
        <div class="field"><label>Note</label><input name="note"/></div>
        <button class="btn btn-primary" type="submit">Enregistrer</button></form>`,
      {
        onMount: (root) => {
          root.querySelector("#c").addEventListener("click", closeModal);
          root.querySelector("#bo-form").addEventListener("submit", async (e) => {
            e.preventDefault();
            const f = new FormData(e.target);
            try {
              await api.post("/blackouts", {
                tool_id: Number(f.get("tool")), start_datetime: new Date(f.get("start")).toISOString(),
                end_datetime: new Date(f.get("end")).toISOString(), reason: f.get("reason"), note: f.get("note") || null,
              });
              closeModal();
              refresh();
            } catch (err) {
              fail(err);
            }
          });
        },
      }
    )
  );
  body.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      await api.delete(`/blackouts/${b.closest(".card").dataset.id}`);
      refresh();
    })
  );
}

async function regles(body, refresh) {
  const [rules, tools] = await Promise.all([api.get("/reservation-rules"), api.get("/agency-tools")]);
  const names = Object.fromEntries(tools.map((t) => [t.id, t.name]));
  body.innerHTML = `
    <p class="card-sub">Une règle peut exiger la validation d'un responsable et/ou limiter la durée d'une réservation. Les responsables et l'administrateur ne sont pas soumis à validation.</p>
    ${rules.length
      ? rules.map((r) => `<div class="card" data-id="${r.id}"><div class="card-row"><div class="card-title">${r.tool_type ? `Type « ${escapeHtml(r.tool_type)} »` : escapeHtml(names[r.agency_tool_id] || `Outil ${r.agency_tool_id}`)}</div>
        ${isManager() ? '<button class="btn btn-sm btn-danger" data-del>Retirer</button>' : ""}</div>
        <div class="card-meta"><span>${r.requires_approval ? "Validation requise" : "Sans validation"}</span><span>${r.max_days ? `Maximum ${r.max_days} jour(s)` : "Durée libre"}</span></div></div>`).join("")
      : `<div class="empty-state">Aucune règle.</div>`}
    ${isManager() ? `<h3>Ajouter une règle</h3><form id="rule-form" class="form-grid card">
      <div class="field"><label>Outil précis</label><select name="tool"><option value="">—</option>${tools.map((t) => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join("")}</select></div>
      ${isAdmin() ? '<div class="field"><label>ou type d\'outil (administrateur)</label><input name="type" placeholder="ex. Moyens d\'accès en hauteur"/></div>' : ""}
      <label><input type="checkbox" name="approval"/> Validation d'un responsable requise</label>
      <div class="field"><label>Durée maximale (jours)</label><input type="number" name="days" min="1" max="365"/></div>
      <button class="btn btn-primary" type="submit">Enregistrer la règle</button></form>` : ""}`;
  body.querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        await api.delete(`/reservation-rules/${b.closest(".card").dataset.id}`);
        refresh();
      } catch (err) {
        fail(err);
      }
    })
  );
  body.querySelector("#rule-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      await api.post("/reservation-rules", {
        agency_tool_id: f.get("tool") ? Number(f.get("tool")) : null,
        tool_type: f.get("type") || null,
        requires_approval: f.has("approval"),
        max_days: f.get("days") ? Number(f.get("days")) : null,
      });
      refresh();
    } catch (err) {
      fail(err);
    }
  });
}

const AT_STATUS = { pending: ["orange", "En attente"], accepted: ["green", "Accepté"], rejected: ["red", "Refusé"], returned: ["gray", "Rendu"], cancelled: ["gray", "Annulé"] };

async function agences(body, refresh) {
  const [transfers, tools, agencies] = await Promise.all([api.get("/agency-transfers"), api.get("/agency-tools"), getAgencies(true)]);
  const me = state.user;
  const canDecide = (t) => isAdmin() || (me.role === "directeur_agence" && me.agency_number === t.to_agency);
  body.innerHTML = `
    ${isManager() ? '<div class="card-actions"><button class="btn btn-sm btn-primary" id="at-new">Proposer un outil à une autre agence</button></div>' : ""}
    ${transfers.length
      ? transfers.map((t) => {
          const [color, label] = AT_STATUS[t.status] || ["gray", t.status];
          return `<div class="card" data-id="${t.id}"><div class="card-row"><div class="card-title">${escapeHtml(t.tool_name)} (${escapeHtml(t.tool_code)})</div><span class="badge badge-${color}">${label}</span></div>
          <div class="card-sub">${escapeHtml(t.from_agency)} → ${escapeHtml(t.to_agency)} · ${t.temporary ? `prêt temporaire${t.planned_return_date ? ` jusqu'au ${formatDate(t.planned_return_date)}` : ""}` : "transfert définitif"}</div>
          ${t.comment ? `<div class="card-sub">${escapeHtml(t.comment)}</div>` : ""}
          <div class="card-actions">
            ${t.status === "pending" && canDecide(t) ? '<button class="btn btn-sm btn-primary" data-act="accept">Accepter</button><button class="btn btn-sm btn-danger" data-act="reject">Refuser</button>' : ""}
            ${t.status === "pending" && isManager() && (t.requested_by_id === me.id || isAdmin()) ? '<button class="btn btn-sm" data-act="cancel">Annuler</button>' : ""}
            ${t.status === "accepted" && t.temporary && isManager() ? '<button class="btn btn-sm" data-act="return">Rendre à l\'agence d\'origine</button>' : ""}
          </div></div>`;
        }).join("")
      : `<div class="empty-state">Aucun transfert entre agences.</div>`}`;
  body.querySelectorAll("[data-act]").forEach((b) =>
    b.addEventListener("click", async () => {
      const id = b.closest(".card").dataset.id;
      try {
        await api.post(`/agency-transfers/${id}/${b.dataset.act}`, b.dataset.act === "reject" ? { comment: (await promptDialog("Motif du refus (optionnel)")) || null } : undefined);
        refresh();
      } catch (err) {
        fail(err);
      }
    })
  );
  body.querySelector("#at-new")?.addEventListener("click", () =>
    openModal(
      `<div class="modal-header"><div class="card-title">Transfert entre agences</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
      <form id="at-form" class="form-grid">
        <div class="field"><label>Outil (disponible)</label><select name="tool">${tools.filter((t) => t.status === "disponible").map((t) => `<option value="${t.id}">${escapeHtml(t.name)} (${escapeHtml(t.unique_code)})</option>`).join("")}</select></div>
        <div class="field"><label>Agence destinataire</label><select name="to">${agencies.filter((a) => a.name !== me.agency_number).map((a) => `<option>${escapeHtml(a.name)}</option>`).join("")}</select></div>
        <label><input type="checkbox" name="temporary"/> Prêt temporaire</label>
        <div class="field"><label>Date de retour (prêt temporaire)</label><input type="date" name="ret"/></div>
        <div class="field"><label>Commentaire</label><input name="comment"/></div>
        <button class="btn btn-primary" type="submit">Envoyer la demande</button></form>`,
      {
        onMount: (root) => {
          root.querySelector("#c").addEventListener("click", closeModal);
          root.querySelector("#at-form").addEventListener("submit", async (e) => {
            e.preventDefault();
            const f = new FormData(e.target);
            try {
              await api.post("/agency-transfers", {
                tool_id: Number(f.get("tool")), to_agency: f.get("to"), temporary: f.has("temporary"),
                planned_return_date: f.get("ret") ? new Date(f.get("ret")).toISOString() : null, comment: f.get("comment") || null,
              });
              toast("Demande envoyée", "success");
              closeModal();
              refresh();
            } catch (err) {
              fail(err);
            }
          });
        },
      }
    )
  );
}
