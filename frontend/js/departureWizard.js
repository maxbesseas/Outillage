import { api, ApiError } from "./api.js";
import { escapeHtml, toast, openModal, closeModal, confirmDialog } from "./ui.js";
import { isAdmin } from "./state.js";
import { getAgencies } from "./agencies.js";

const fail = (err) => toast(err instanceof ApiError ? err.message : "Erreur", "error");

function list(title, items, render) {
  return items.length
    ? `<div class="card"><div class="card-title">${title} (${items.length})</div><div class="card-sub">${items.map(render).join(" · ")}</div></div>`
    : "";
}

/** Assistant « Départ d'un salarié » : réaffecte le matériel puis désactive le compte. */
export async function openDepartureWizard(user, team, onDone) {
  let summary;
  try {
    summary = await api.get(`/users/${user.id}/departure-summary`);
  } catch (err) {
    fail(err);
    return;
  }
  const candidates = team.filter((u) => u.id !== user.id && u.is_active && (isAdmin() || u.agency_number === user.agency_number));
  const sameRole = candidates.filter((u) => u.role === user.role);
  const agencies = isAdmin() ? await getAgencies(true) : [];

  openModal(
    `
    <div class="modal-header"><div class="card-title">Départ de ${escapeHtml(user.full_name)}</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    ${list("Outils personnels possédés", summary.owned_tools, (t) => escapeHtml(t.name))}
    ${list("Outils personnels détenus", summary.held_tools, (t) => escapeHtml(t.name))}
    ${list("EPI assignés", summary.epi, (t) => escapeHtml(t.name))}
    ${list("Dotations", summary.dotations, (t) => escapeHtml(t.name))}
    ${list("Réservations actives", summary.loans, (l) => `#${l.id} (${l.status})`)}
    ${list("Prêts externes en cours", summary.external_transfers, (t) => escapeHtml(t.recipient))}
    ${list("Transferts entre collègues à régler", summary.peer_transfers, (p) => `#${p.id}`)}
    ${list("Collaborateurs rattachés", summary.subordinates, (u) => escapeHtml(u.full_name))}
    <form id="dep-form" class="form-grid">
      <div class="field"><label>Reprendre le matériel : nouveau détenteur</label>
        <select name="to">${candidates.map((u) => `<option value="${u.id}">${escapeHtml(u.full_name)}</option>`).join("")}</select></div>
      <label><input type="checkbox" name="ownership" checked/> Transférer aussi la propriété des outils personnels</label>
      ${summary.loans.length ? '<label><input type="checkbox" name="loans"/> Transférer les réservations actives</label>' : ""}
      ${summary.external_transfers.length ? '<label><input type="checkbox" name="external"/> Transférer les prêts externes en cours</label>' : ""}
      ${summary.subordinates.length ? `<div class="field"><label>Nouveau responsable de ses collaborateurs</label>
        <select name="subs">${sameRole.map((u) => `<option value="${u.id}">${escapeHtml(u.full_name)}</option>`).join("") || '<option value="">Aucun collègue de même rôle</option>'}</select></div>` : ""}
      <label><input type="checkbox" name="deactivate" checked/> Désactiver le compte ensuite</label>
      <button type="submit" class="btn btn-primary" ${candidates.length ? "" : "disabled"}>Confirmer le départ</button>
    </form>
    ${isAdmin() ? `<h4>Ou changement d'agence</h4>
      <form id="agency-form" class="form-grid"><div class="field"><label>Nouvelle agence</label>
        <select name="agency">${agencies.filter((a) => a.name !== user.agency_number).map((a) => `<option>${escapeHtml(a.name)}</option>`).join("")}</select></div>
        <label><input type="checkbox" name="subs"/> Déplacer aussi ses collaborateurs</label>
        <button type="submit" class="btn">Changer d'agence</button></form>` : ""}`,
    {
      onMount: (root) => {
        root.querySelector("#c").addEventListener("click", closeModal);
        root.querySelector("#dep-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          if (!(await confirmDialog(`Confirmer le départ de ${user.full_name} ?`, { danger: true }))) return;
          try {
            const res = await api.post(`/users/${user.id}/depart`, {
              to_user_id: Number(f.get("to")),
              transfer_ownership: f.has("ownership"),
              transfer_loans: f.has("loans"),
              transfer_external: f.has("external"),
              reassign_subordinates_to: f.get("subs") ? Number(f.get("subs")) : null,
              deactivate: f.has("deactivate"),
            });
            toast(`Matériel réaffecté (${res.counts.personal_tools || 0} outil(s), ${res.counts.epi || 0} EPI)`, "success");
            closeModal();
            onDone();
          } catch (err) {
            fail(err);
          }
        });
        root.querySelector("#agency-form")?.addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          try {
            await api.post(`/users/${user.id}/change-agency`, { agency_number: f.get("agency"), include_subordinates: f.has("subs") });
            toast("Agence modifiée", "success");
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
