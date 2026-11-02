import { api, ApiError } from "./api.js";
import { escapeHtml, toast, openModal, closeModal } from "./ui.js";
import { isManager } from "./state.js";

const fail = (err) => toast(err instanceof ApiError ? err.message : "Erreur", "error");
const EXIT_REASONS = { rebut: "Mise au rebut", vendu: "Vendu", donne: "Donné", vole: "Volé (non retrouvé)", perdu: "Perdu (non retrouvé)" };

export async function openAccessories(tool) {
  const render = async () => {
    const items = await api.get(`/agency-tools/${tool.id}/accessories`);
    openModal(
      `<div class="modal-header"><div class="card-title">Accessoires — ${escapeHtml(tool.name)}</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
      ${items.length
        ? items.map((a) => `<div class="card" data-id="${a.id}"><div class="card-row"><div class="card-title">${escapeHtml(a.name)} × ${a.quantity}</div>
          ${isManager() ? '<button class="btn btn-sm btn-danger" data-del>Retirer</button>' : ""}</div>
          <div class="card-sub">${a.required ? "Contrôlé à chaque retour" : "Facultatif"}${a.note ? ` · ${escapeHtml(a.note)}` : ""}</div></div>`).join("")
        : `<div class="empty-state">Aucun accessoire enregistré.</div>`}
      ${isManager() ? `<form id="acc-form" class="form-grid card"><div class="field-row"><div class="field"><label>Accessoire</label><input name="name" required/></div>
        <div class="field"><label>Quantité</label><input type="number" name="quantity" min="1" value="1"/></div></div>
        <label><input type="checkbox" name="required" checked/> À vérifier au retour</label>
        <button class="btn btn-primary" type="submit">Ajouter</button></form>` : ""}`,
      {
        onMount: (root) => {
          root.querySelector("#c").addEventListener("click", closeModal);
          root.querySelectorAll("[data-del]").forEach((b) =>
            b.addEventListener("click", async () => {
              await api.delete(`/agency-tools/${tool.id}/accessories/${b.closest(".card").dataset.id}`);
              render();
            })
          );
          root.querySelector("#acc-form")?.addEventListener("submit", async (e) => {
            e.preventDefault();
            const f = new FormData(e.target);
            try {
              await api.post(`/agency-tools/${tool.id}/accessories`, { name: f.get("name"), quantity: Number(f.get("quantity")), required: f.has("required") });
              render();
            } catch (err) {
              fail(err);
            }
          });
        },
      }
    );
  };
  await render();
}

export function openExitForm(tool, onDone) {
  openModal(
    `<div class="modal-header"><div class="card-title">Sortie de parc — ${escapeHtml(tool.name)}</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    <form id="exit-form" class="form-grid">
      <p class="card-sub">L'outil disparaît des listes courantes mais reste dans l'historique et les statistiques financières. Selon les réglages, la demande doit être validée par un directeur.</p>
      <div class="field"><label>Motif</label><select name="reason">${Object.entries(EXIT_REASONS).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}</select></div>
      <div class="field"><label>Date de sortie</label><input type="date" name="date" value="${new Date().toISOString().slice(0, 10)}"/></div>
      <div class="field"><label>Valeur résiduelle / de cession (€)</label><input type="number" name="residual" min="0" step="0.01"/></div>
      <div class="field"><label>Justificatif / note</label><textarea name="note" rows="2"></textarea></div>
      <button class="btn btn-danger" type="submit">Envoyer</button>
    </form>`,
    {
      onMount: (root) => {
        root.querySelector("#c").addEventListener("click", closeModal);
        root.querySelector("#exit-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          try {
            const res = await api.post(`/agency-tools/${tool.id}/exit`, {
              reason: f.get("reason"),
              exit_date: f.get("date") ? new Date(f.get("date")).toISOString() : null,
              residual_value: f.get("residual") ? Number(f.get("residual")) : null,
              note: f.get("note") || null,
            });
            toast(res.status === "approved" ? "Outil sorti du parc" : "Demande envoyée pour validation", "success");
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
