import { api, ApiError } from "../api.js";
import { escapeHtml, formatDate, formatDateTime, toast, openModal, closeModal } from "../ui.js";
import { isManager } from "../state.js";
import { compressImage } from "../images.js";

const STATUS = {
  ouvert: ["orange", "Ouvert"],
  diagnostic: ["blue", "Diagnostic"],
  en_reparation: ["blue", "En réparation"],
  attente_piece: ["orange", "Attente pièce"],
  repare: ["green", "Réparé"],
  irreparable: ["red", "Irréparable"],
  clos: ["gray", "Clos"],
};
const NEXT = {
  ouvert: ["diagnostic", "en_reparation", "attente_piece", "repare", "irreparable"],
  diagnostic: ["en_reparation", "attente_piece", "repare", "irreparable"],
  en_reparation: ["attente_piece", "repare", "irreparable"],
  attente_piece: ["en_reparation", "repare", "irreparable"],
  repare: ["clos"],
  irreparable: ["clos"],
  clos: [],
};
const CATEGORY = { panne: "Panne", casse: "Casse", usure: "Usure", accessoire_manquant: "Accessoire manquant", perte: "Perte", vol: "Vol", autre: "Autre" };
const SEVERITY = { faible: "gray", moyenne: "blue", haute: "orange", critique: "red" };
const KIND_LABEL = { agency: "Outil d'agence", epi: "EPI", personal: "Outil personnel" };
const fail = (err) => toast(err instanceof ApiError ? err.message : "Erreur", "error");

let view = { tab: "tickets", openOnly: true };

function card(t) {
  const [color, label] = STATUS[t.status] || ["gray", t.status];
  return `<div class="card" data-id="${t.id}">
    <div class="card-row"><div class="card-title">#${t.id} · ${escapeHtml(t.tool.name)}</div>
      <span class="badge badge-${color}"><span class="dot"></span>${label}</span></div>
    <div class="card-sub">${escapeHtml(KIND_LABEL[t.tool_kind] || "")} · ${escapeHtml(CATEGORY[t.category] || t.category)}${t.description ? ` — ${escapeHtml(t.description)}` : ""}</div>
    <div class="card-meta">
      <span class="badge badge-${SEVERITY[t.severity] || "gray"}">${escapeHtml(t.severity)}</span>
      <span>Ouvert le ${formatDate(t.opened_at)}${t.opened_by_name ? ` par ${escapeHtml(t.opened_by_name)}` : ""}</span>
      <span>${t.age_days} jour(s)</span>
      ${t.warranty_claim ? '<span class="badge badge-green">Garantie</span>' : ""}
      ${t.expected_return_date ? `<span>Retour prévu : ${formatDate(t.expected_return_date)}</span>` : ""}
    </div></div>`;
}

export async function renderMaintenance(app) {
  const managerView = isManager();
  const [tickets, stats, exits] = await Promise.all([
    api.get(`/maintenance-tickets?limit=300${view.openOnly ? "&open_only=true" : ""}`),
    managerView ? api.get("/maintenance-tickets/stats") : null,
    managerView ? api.get("/exit-requests") : [],
  ]);

  app.innerHTML = `
    <div class="section-header"><h1>Maintenance</h1><div class="section-links"><a href="#/stock">Stock</a></div></div>
    ${
      stats
        ? `<div class="stat-grid">
      <div class="stat-tile"><div class="stat-value">${stats.open}</div><div class="stat-label">Tickets ouverts</div></div>
      <div class="stat-tile"><div class="stat-value">${stats.avg_repair_days ?? "-"}</div><div class="stat-label">Délai moyen de réparation (jours)</div></div>
      <div class="stat-tile"><div class="stat-value">${stats.total_cost.toLocaleString("fr-FR")} €</div><div class="stat-label">Coût des réparations</div></div>
      <div class="stat-tile"><div class="stat-value">${stats.total}</div><div class="stat-label">Tickets au total</div></div></div>`
        : ""
    }
    <div class="tag-row" id="m-tabs">
      <button data-tab="tickets" class="${view.tab === "tickets" ? "active" : ""}">Tickets</button>
      ${managerView ? `<button data-tab="exits" class="${view.tab === "exits" ? "active" : ""}">Sorties de parc (${exits.length})</button>` : ""}
    </div>
    <div id="m-body"></div>`;

  document.querySelectorAll("#m-tabs button").forEach((b) =>
    b.addEventListener("click", () => {
      view.tab = b.dataset.tab;
      renderMaintenance(app);
    })
  );
  const body = document.getElementById("m-body");

  if (view.tab === "exits" && managerView) {
    body.innerHTML = exits.length
      ? exits
          .map(
            (x) => `<div class="card" data-id="${x.id}"><div class="card-row"><div class="card-title">${escapeHtml(x.tool_name)} (${escapeHtml(x.tool_code)})</div>
        <span class="badge badge-orange">À valider</span></div>
        <div class="card-sub">${escapeHtml(x.reason)}${x.note ? ` — ${escapeHtml(x.note)}` : ""}${x.residual_value != null ? ` · ${x.residual_value} €` : ""} · demandé par ${escapeHtml(x.requested_by || "-")}</div>
        <div class="card-actions"><button class="btn btn-sm btn-primary" data-act="approve">Valider</button><button class="btn btn-sm btn-danger" data-act="reject">Refuser</button></div></div>`
          )
          .join("")
      : `<div class="empty-state">Aucune demande de sortie de parc en attente.</div>`;
    body.querySelectorAll("[data-act]").forEach((b) =>
      b.addEventListener("click", async () => {
        try {
          await api.post(`/exit-requests/${b.closest(".card").dataset.id}/${b.dataset.act}`);
          renderMaintenance(app);
        } catch (err) {
          fail(err);
        }
      })
    );
    return;
  }

  body.innerHTML = `
    <div class="tag-row"><button data-open="1" class="${view.openOnly ? "active" : ""}">Ouverts</button><button data-open="0" class="${view.openOnly ? "" : "active"}">Tous</button></div>
    ${tickets.length ? tickets.map(card).join("") : `<div class="empty-state">Aucun ticket.</div>`}`;
  body.querySelectorAll("[data-open]").forEach((b) =>
    b.addEventListener("click", () => {
      view.openOnly = b.dataset.open === "1";
      renderMaintenance(app);
    })
  );
  body.querySelectorAll(".card[data-id]").forEach((el) =>
    el.addEventListener("click", () => openTicket(Number(el.dataset.id), () => renderMaintenance(app)))
  );
}

async function openTicket(id, onDone) {
  const t = await api.get(`/maintenance-tickets/${id}`);
  const [color, label] = STATUS[t.status] || ["gray", t.status];
  const manager = isManager();
  const next = manager ? NEXT[t.status] || [] : [];

  openModal(
    `
    <div class="modal-header"><div class="card-title">Ticket #${t.id} — ${escapeHtml(t.tool.name)}</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    <div class="card-meta"><span class="badge badge-${color}">${label}</span><span>${escapeHtml(CATEGORY[t.category] || t.category)}</span>
      <span class="badge badge-${SEVERITY[t.severity]}">${escapeHtml(t.severity)}</span>
      ${t.tool.warranty.active ? `<span class="badge badge-green">Sous garantie jusqu'au ${formatDate(t.tool.warranty.expires)}</span>` : ""}</div>
    ${t.description ? `<p>${escapeHtml(t.description)}</p>` : ""}
    ${t.resolution ? `<div class="card-sub">Résolution : ${escapeHtml(t.resolution)}</div>` : ""}
    ${
      manager && next.length
        ? `<form id="tr-form" class="form-grid card"><h4>Faire avancer le ticket</h4>
        <div class="field-row"><div class="field"><label>Nouveau statut</label>
          <select name="status">${next.map((s) => `<option value="${s}">${STATUS[s][1]}</option>`).join("")}</select></div>
          <div class="field" id="state-field"><label>État après réparation (0-5)</label><input type="number" name="state_after" min="0" max="5" value="5"/></div></div>
        <div class="field"><label>Résolution / commentaire</label><input name="comment"/></div>
        <button class="btn btn-primary" type="submit">Valider</button></form>`
        : ""
    }
    ${
      manager && !["clos"].includes(t.status)
        ? `<form id="ed-form" class="form-grid card"><h4>Suivi</h4>
        <div class="field-row"><div class="field"><label>Prestataire</label>
          <select name="provider"><option value="">—</option>${["interne", "fournisseur", "sav"].map((p) => `<option ${t.provider === p ? "selected" : ""}>${p}</option>`).join("")}</select></div>
          <div class="field"><label>Retour prévu</label><input type="date" name="expected" value="${t.expected_return_date ? t.expected_return_date.slice(0, 10) : ""}"/></div></div>
        <div class="field-row"><div class="field"><label>Coût estimé (€)</label><input type="number" step="0.01" min="0" name="estimated" value="${t.estimated_cost ?? ""}"/></div>
          <div class="field"><label>Coût réel (€)</label><input type="number" step="0.01" min="0" name="actual" value="${t.actual_cost ?? ""}"/></div></div>
        <div class="field"><label>Pièces</label><input name="parts" value="${escapeHtml(t.parts || "")}"/></div>
        <label><input type="checkbox" name="warranty" ${t.warranty_claim ? "checked" : ""}/> Dossier de garantie / SAV</label>
        <div class="field"><label>N° de dossier SAV</label><input name="case" value="${escapeHtml(t.warranty_case_number || "")}"/></div>
        <button class="btn" type="submit">Enregistrer le suivi</button></form>`
        : ""
    }
    <h4>Pièces jointes</h4>
    ${t.attachments.map((a) => `<div class="card-sub"><a href="${escapeHtml(a.path)}" target="_blank" rel="noopener">${escapeHtml(a.kind)} — ${escapeHtml(a.filename || a.path)}</a></div>`).join("") || '<div class="card-sub">Aucune.</div>'}
    <form id="att-form" class="filter-bar"><select name="kind"><option value="photo">Photo</option>${manager ? '<option value="devis">Devis</option><option value="facture">Facture</option>' : ""}</select>
      <input type="file" name="file" required/><button class="btn btn-sm">Ajouter</button></form>
    <h4>Historique</h4>
    ${t.comments.map((c) => `<div class="card-sub"><strong>${escapeHtml(c.user_name || "Système")}</strong> · ${escapeHtml(formatDateTime(c.created_at))} — ${escapeHtml(c.body)}</div>`).join("")}
    <form id="cm-form" class="filter-bar"><input name="body" placeholder="Ajouter un commentaire" required/><button class="btn btn-sm">Envoyer</button></form>`,
    {
      onMount: (root) => {
        root.querySelector("#c").addEventListener("click", closeModal);
        const reload = () => {
          closeModal();
          onDone();
          openTicket(id, onDone);
        };
        const stateField = root.querySelector("#state-field");
        const trStatus = root.querySelector('#tr-form [name="status"]');
        const syncState = () => stateField && stateField.classList.toggle("hidden", trStatus.value !== "repare");
        if (trStatus) {
          trStatus.addEventListener("change", syncState);
          syncState();
        }
        root.querySelector("#tr-form")?.addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          try {
            await api.post(`/maintenance-tickets/${id}/transition`, {
              status: f.get("status"),
              state_after: f.get("status") === "repare" ? Number(f.get("state_after")) : null,
              resolution: ["repare", "irreparable"].includes(f.get("status")) ? f.get("comment") || null : null,
              comment: f.get("comment") || null,
            });
            reload();
          } catch (err) {
            fail(err);
          }
        });
        root.querySelector("#ed-form")?.addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          try {
            await api.patch(`/maintenance-tickets/${id}`, {
              provider: f.get("provider") || null,
              expected_return_date: f.get("expected") ? new Date(f.get("expected")).toISOString() : null,
              estimated_cost: f.get("estimated") ? Number(f.get("estimated")) : null,
              actual_cost: f.get("actual") ? Number(f.get("actual")) : null,
              parts: f.get("parts") || null,
              warranty_claim: f.has("warranty"),
              warranty_case_number: f.get("case") || null,
            });
            toast("Suivi enregistré", "success");
            reload();
          } catch (err) {
            fail(err);
          }
        });
        root.querySelector("#att-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          const kind = f.get("kind");
          let file = f.get("file");
          try {
            if (kind === "photo") file = await compressImage(file);
            await api.upload(`/maintenance-tickets/${id}/attachments?kind=${kind}`, file);
            reload();
          } catch (err) {
            fail(err);
          }
        });
        root.querySelector("#cm-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          try {
            await api.post(`/maintenance-tickets/${id}/comments`, { body: new FormData(e.target).get("body") });
            reload();
          } catch (err) {
            fail(err);
          }
        });
      },
    }
  );
}
