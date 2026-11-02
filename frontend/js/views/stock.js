import { api, ApiError } from "../api.js";
import { escapeHtml, formatDateTime, toast, openModal, closeModal } from "../ui.js";
import { isManager } from "../state.js";
import { getTeam } from "../usersCache.js";

const fail = (err) => toast(err instanceof ApiError ? err.message : "Erreur", "error");
let lowOnly = false;

export async function renderStock(app) {
  const items = await api.get(`/stock/items?low_only=${lowOnly}`);
  app.innerHTML = `
    <div class="section-header"><h1>Stock de consommables</h1>
      <div class="section-links"><a href="#/maintenance">Maintenance</a>${isManager() ? '<button class="btn btn-sm btn-primary" id="new-item">Nouvel article</button>' : ""}</div></div>
    <div class="tag-row"><button data-low="0" class="${lowOnly ? "" : "active"}">Tous</button><button data-low="1" class="${lowOnly ? "active" : ""}">Sous le seuil</button></div>
    ${items.length ? items.map((i) => `<div class="card" data-id="${i.id}">
      <div class="card-row"><div class="card-title">${escapeHtml(i.name)}${i.reference ? ` <span class="card-sub">${escapeHtml(i.reference)}</span>` : ""}</div>
        <span class="badge ${i.low ? "badge-red" : "badge-green"}"><span class="dot"></span>${i.quantity} ${escapeHtml(i.unit)}</span></div>
      <div class="card-meta"><span>Seuil : ${i.threshold}</span>${i.location ? `<span>${escapeHtml(i.location)}</span>` : ""}</div>
      <div class="card-actions">${isManager() ? '<button class="btn btn-sm" data-act="move">Mouvement</button>' : ""}<button class="btn btn-sm" data-act="history">Historique</button></div></div>`).join("")
      : `<div class="empty-state">Aucun article.</div>`}`;

  app.querySelectorAll("[data-low]").forEach((b) => b.addEventListener("click", () => { lowOnly = b.dataset.low === "1"; renderStock(app); }));
  const refresh = () => renderStock(app);

  document.getElementById("new-item")?.addEventListener("click", () =>
    openModal(
      `<div class="modal-header"><div class="card-title">Nouvel article</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
      <form id="i-form" class="form-grid">
        <div class="field"><label>Désignation</label><input name="name" required/></div>
        <div class="field-row"><div class="field"><label>Référence</label><input name="reference"/></div><div class="field"><label>Unité</label><input name="unit" value="pièce"/></div></div>
        <div class="field-row"><div class="field"><label>Quantité initiale</label><input type="number" name="quantity" min="0" step="any" value="0"/></div>
          <div class="field"><label>Seuil d'alerte</label><input type="number" name="threshold" min="0" step="any" value="0"/></div></div>
        <div class="field"><label>Emplacement</label><input name="location"/></div>
        <button class="btn btn-primary" type="submit">Créer</button></form>`,
      {
        onMount: (root) => {
          root.querySelector("#c").addEventListener("click", closeModal);
          root.querySelector("#i-form").addEventListener("submit", async (e) => {
            e.preventDefault();
            const f = new FormData(e.target);
            try {
              await api.post("/stock/items", { name: f.get("name"), reference: f.get("reference") || null, unit: f.get("unit") || "pièce",
                quantity: Number(f.get("quantity")), threshold: Number(f.get("threshold")), location: f.get("location") || null });
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

  app.querySelectorAll("[data-act]").forEach((b) =>
    b.addEventListener("click", async () => {
      const item = items.find((i) => i.id === Number(b.closest(".card").dataset.id));
      if (b.dataset.act === "history") {
        const moves = await api.get(`/stock/items/${item.id}/movements`);
        openModal(`<div class="modal-header"><div class="card-title">${escapeHtml(item.name)}</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
          ${moves.map((m) => `<div class="card"><div class="card-row"><div class="card-title">${escapeHtml(m.kind)} ${m.quantity}</div><div class="card-sub">Solde ${m.balance_after}</div></div>
            <div class="card-sub">${escapeHtml(formatDateTime(m.created_at))} · ${escapeHtml(m.user_name || "-")}${m.to_user_name ? ` → ${escapeHtml(m.to_user_name)}` : ""}${m.site ? ` · ${escapeHtml(m.site)}` : ""}</div></div>`).join("") || '<div class="empty-state">Aucun mouvement.</div>'}`,
          { onMount: (root) => root.querySelector("#c").addEventListener("click", closeModal) });
        return;
      }
      const team = await getTeam();
      let sites = [];
      try {
        sites = (await api.get("/sites?status_filter=actif")).filter((s) => (s.agency_number || null) === (item.agency_number || null));
      } catch {
        sites = [];
      }
      openModal(
        `<div class="modal-header"><div class="card-title">Mouvement — ${escapeHtml(item.name)}</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
        <form id="m-form" class="form-grid">
          <div class="field"><label>Type</label><select name="kind"><option value="sortie">Sortie</option><option value="entree">Entrée</option><option value="inventaire">Inventaire (fixer le stock)</option></select></div>
          <div class="field"><label>Quantité</label><input type="number" name="quantity" min="0" step="any" required/></div>
          <div class="field"><label>Remis à</label><select name="to"><option value="">—</option>${team.map((u) => `<option value="${u.id}">${escapeHtml(u.full_name)}</option>`).join("")}</select></div>
          <div class="field"><label>Chantier</label>${
            sites.length
              ? `<select name="site_id"><option value="">—</option>${sites.map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join("")}</select>`
              : '<input name="site"/>'
          }</div>
          <div class="field"><label>Note</label><input name="note"/></div>
          <button class="btn btn-primary" type="submit">Enregistrer</button></form>`,
        {
          onMount: (root) => {
            root.querySelector("#c").addEventListener("click", closeModal);
            root.querySelector("#m-form").addEventListener("submit", async (e) => {
              e.preventDefault();
              const f = new FormData(e.target);
              try {
                await api.post(`/stock/items/${item.id}/movements`, { kind: f.get("kind"), quantity: Number(f.get("quantity")),
                  to_user_id: f.get("to") ? Number(f.get("to")) : null,
                  site: f.get("site") || null, site_id: f.get("site_id") ? Number(f.get("site_id")) : null, note: f.get("note") || null });
                closeModal();
                refresh();
              } catch (err) {
                fail(err);
              }
            });
          },
        }
      );
    })
  );
}
