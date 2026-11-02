import { api, ApiError } from "../api.js";
import { escapeHtml, formatDate, toast, openModal, closeModal } from "../ui.js";
import { isManager } from "../state.js";

const BUCKETS = [
  ["expired", "Échus", "red"],
  ["missing", "Jamais étalonnés", "orange"],
  ["soon", "Bientôt échus", "blue"],
  ["ok", "À jour", "green"],
];

export async function renderCalibrations(app) {
  const overview = await api.get("/calibrations/overview");

  app.innerHTML = `
    <div class="section-header">
      <h1>Étalonnages</h1>
      <div class="section-links"><a href="#/controles">Contrôles</a></div>
    </div>
    <p class="card-sub">Seuls les types marqués « instrument à étalonner » dans les périodicités apparaissent ici.</p>
    ${BUCKETS.map(
      ([key, label, color]) => `
      <h3><span class="badge badge-${color}"><span class="dot"></span>${label} (${overview[key].length})</span></h3>
      ${
        overview[key].length
          ? overview[key]
              .map(
                (t) => `<div class="card" data-id="${t.id}">
          <div class="card-row"><div class="card-title">${escapeHtml(t.name)}</div>
            ${isManager() ? '<button class="btn btn-sm btn-primary" data-action="add">Enregistrer un étalonnage</button>' : ""}</div>
          <div class="card-sub">${escapeHtml(t.type || "-")} · ${escapeHtml(t.code)}</div>
          <div class="card-meta"><span>Dernier : ${t.last ? formatDate(t.last) : "-"}</span><span>Échéance : ${t.due ? formatDate(t.due) : "-"}</span>
            ${t.certificate_number ? `<span>Certificat ${escapeHtml(t.certificate_number)}</span>` : ""}</div></div>`
              )
              .join("")
          : `<div class="empty-state">Aucun instrument.</div>`
      }`
    ).join("")}
  `;

  app.querySelectorAll('[data-action="add"]').forEach((btn) =>
    btn.addEventListener("click", () => {
      const id = Number(btn.closest(".card").dataset.id);
      openModal(
        `<div class="modal-header"><div class="card-title">Nouvel étalonnage</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
        <form id="cal-form" class="form-grid">
          <div class="field"><label>Date</label><input type="date" name="calibrated_at" value="${new Date().toISOString().slice(0, 10)}" required/></div>
          <div class="field"><label>Prestataire</label><input name="provider"/></div>
          <div class="field"><label>N° de certificat</label><input name="certificate_number"/></div>
          <div class="field"><label>Coût (€)</label><input type="number" name="cost" step="0.01" min="0"/></div>
          <div class="field"><label>Résultat</label><select name="result"><option value="conforme">Conforme</option><option value="non_conforme">Non conforme</option></select></div>
          <div class="field"><label>Certificat (PDF)</label><input type="file" name="certificate" accept="application/pdf"/></div>
          <button type="submit" class="btn btn-primary">Enregistrer</button>
        </form>`,
        {
          onMount: (root) => {
            root.querySelector("#c").addEventListener("click", closeModal);
            root.querySelector("#cal-form").addEventListener("submit", async (e) => {
              e.preventDefault();
              const f = new FormData(e.target);
              try {
                const created = await api.post("/calibrations", {
                  tool_id: id,
                  calibrated_at: new Date(f.get("calibrated_at")).toISOString(),
                  provider: f.get("provider") || null,
                  certificate_number: f.get("certificate_number") || null,
                  cost: f.get("cost") ? Number(f.get("cost")) : null,
                  result: f.get("result"),
                });
                const file = f.get("certificate");
                if (file && file.size) await api.upload(`/calibrations/${created.id}/certificate`, file);
                toast("Étalonnage enregistré", "success");
                closeModal();
                renderCalibrations(app);
              } catch (err) {
                toast(err instanceof ApiError ? err.message : "Erreur", "error");
              }
            });
          },
        }
      );
    })
  );
}
