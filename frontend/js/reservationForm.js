import { api, ApiError } from "./api.js";
import { openModal, closeModal, toast, toDatetimeLocal, escapeHtml } from "./ui.js";
import { isManager, state } from "./state.js";
import { getTeam } from "./usersCache.js";

const WAIT_HINTS = ["déjà réservé", "pas disponible", "Indisponible", "indisponible", "proposé à une personne"];

export async function openReserveForm(tool, onDone, prefillStart) {
  const start = prefillStart ? new Date(prefillStart) : new Date();
  if (!prefillStart) {
    start.setMinutes(0, 0, 0);
    start.setHours(start.getHours() + 1);
  } else {
    start.setHours(8, 0, 0, 0);
  }
  const end = new Date(start.getTime() + 2 * 60 * 60 * 1000);
  const team = isManager() ? await getTeam() : [];
  let sites = [];
  try {
    sites = (await api.get("/sites?status_filter=actif")).filter((s) => (s.agency_number || null) === (tool.agency_number || null));
  } catch {
    sites = [];
  }

  openModal(
    `
    <div class="modal-header">
      <div class="card-title">Réserver — ${escapeHtml(tool.name)}</div>
      <button class="btn btn-ghost btn-sm" id="reserve-close">Fermer</button>
    </div>
    <form id="reserve-form" class="form-grid">
      ${
        team.length > 1
          ? `<div class="field"><label>Pour</label><select name="borrower_id">
              <option value="${state.user.id}">Moi-même</option>
              ${team.filter((u) => u.id !== state.user.id && u.is_active).map((u) => `<option value="${u.id}">${escapeHtml(u.full_name)}</option>`).join("")}
            </select></div>`
          : ""
      }
      ${
        sites.length
          ? `<div class="field"><label>Chantier</label><select name="site_id" id="site-select">
              <option value="">— Aucun —</option>
              ${sites.map((s) => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join("")}
              <option value="other">Autre (saisie libre)</option></select></div>
            <div class="field hidden" id="site-free"><label>Nom du chantier</label><input type="text" name="site" autocomplete="off"/></div>`
          : `<div class="field"><label>Chantier</label><input type="text" name="site" autocomplete="off"/></div>`
      }
      <div class="field"><label>Début</label><input type="datetime-local" name="start_datetime" value="${toDatetimeLocal(start)}" required/></div>
      <div class="field"><label>Fin prévue</label><input type="datetime-local" name="end_datetime_planned" value="${toDatetimeLocal(end)}" required/></div>
      <div class="field-row">
        <div class="field"><label>Répétition</label>
          <select name="frequency"><option value="">Aucune</option><option value="daily">Chaque jour</option><option value="weekly">Chaque semaine</option></select></div>
        <div class="field hidden" id="until-field"><label>Jusqu'au</label><input type="date" name="until"/></div>
      </div>
      <div class="field"><label>État constaté au départ (0-5)</label><input type="number" name="state_before" min="0" max="5" value="${tool.state}" inputmode="numeric"/></div>
      <div class="field"><label>Commentaire</label><textarea name="comment" rows="2"></textarea></div>
      <p class="card-sub" id="reserve-hint">Une réservation qui commence plus tard est à retirer au début du créneau ; l'outil reste disponible d'ici là.</p>
      <div id="reserve-error"></div>
      <button type="submit" class="btn btn-primary">Réserver</button>
    </form>
  `,
    {
      onMount: (root) => {
        root.querySelector("#reserve-close").addEventListener("click", closeModal);
        const siteSelect = root.querySelector("#site-select");
        if (siteSelect) {
          siteSelect.addEventListener("change", () => {
            root.querySelector("#site-free").classList.toggle("hidden", siteSelect.value !== "other");
          });
        }
        const frequency = root.querySelector('[name="frequency"]');
        frequency.addEventListener("change", () => {
          root.querySelector("#until-field").classList.toggle("hidden", !frequency.value);
        });

        root.querySelector("#reserve-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const data = Object.fromEntries(new FormData(e.target).entries());
          const base = {
            tool_id: tool.id,
            site: data.site_id === "other" || !data.site_id ? data.site || null : null,
            comment: data.comment || null,
            start_datetime: new Date(data.start_datetime).toISOString(),
            end_datetime_planned: new Date(data.end_datetime_planned).toISOString(),
          };
          if (data.site_id && data.site_id !== "other") base.site_id = Number(data.site_id);
          if (data.borrower_id && Number(data.borrower_id) !== state.user.id) base.borrower_id = Number(data.borrower_id);
          try {
            if (data.frequency) {
              if (!data.until) throw new ApiError("Indiquez la date de fin de la répétition", 400);
              const res = await api.post("/loans/recurring", {
                ...base,
                frequency: data.frequency,
                until: new Date(`${data.until}T23:59:59`).toISOString(),
              });
              toast(`${res.count} réservations créées`, "success");
            } else {
              await api.post("/loans", { ...base, state_before: data.state_before !== "" ? Number(data.state_before) : null });
              toast("Réservation créée", "success");
            }
            closeModal();
            if (onDone) onDone();
          } catch (err) {
            const message = err instanceof ApiError ? err.message : "Erreur lors de la réservation";
            toast(message, "error");
            if (WAIT_HINTS.some((h) => message.includes(h))) {
              const box = root.querySelector("#reserve-error");
              box.innerHTML = `<div class="alert-block warning"><div class="card-sub">${escapeHtml(message)}</div>
                <button type="button" class="btn btn-sm" id="join-wait">Me prévenir quand l'outil est disponible</button></div>`;
              box.querySelector("#join-wait").addEventListener("click", async () => {
                try {
                  await api.post("/waitlist", {
                    tool_id: tool.id,
                    start_datetime: base.start_datetime,
                    end_datetime: base.end_datetime_planned,
                    site: base.site,
                  });
                  toast("Vous êtes en liste d'attente", "success");
                  closeModal();
                  if (onDone) onDone();
                } catch (waitErr) {
                  toast(waitErr instanceof ApiError ? waitErr.message : "Erreur", "error");
                }
              });
            }
          }
        });
      },
    }
  );
}
