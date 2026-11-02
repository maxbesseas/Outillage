import { api, ApiError } from "./api.js";
import { escapeHtml, toast, openModal, closeModal } from "./ui.js";
import { compressImage } from "./images.js";

const DETAIL_PATH = { agency: "/agency-tools", epi: "/epi", personal: "/personal-tools" };
const AGENCY_STATUSES = [
  ["disponible", "Disponible"],
  ["reparation", "En réparation"],
  ["hors_service", "Hors service"],
];

export async function openInspectionForm(kind, toolId, onDone) {
  const tool = await api.get(`${DETAIL_PATH[kind]}/${toolId}`);
  const { items, policy } = await api.get(`/inspections/template?kind=${kind}&type=${encodeURIComponent(tool.type || "")}`);

  const status = AGENCY_STATUSES.some(([v]) => v === tool.status) ? tool.status : "disponible";

  const checklist = items.length
    ? `<div class="checklist">
        <h4>Points de contrôle</h4>
        ${items
          .map(
            (it) => `
          <div class="check-item" data-id="${escapeHtml(it.id)}">
            <div class="check-label">${escapeHtml(it.label)}${it.required ? ' <span class="badge badge-gray">obligatoire</span>' : ""}</div>
            <div class="check-choices" role="radiogroup" aria-label="${escapeHtml(it.label)}">
              <label><input type="radio" name="ck-${escapeHtml(it.id)}" value="ok"/> Conforme</label>
              <label><input type="radio" name="ck-${escapeHtml(it.id)}" value="ko"/> Non conforme</label>
              <label><input type="radio" name="ck-${escapeHtml(it.id)}" value="na"/> Sans objet</label>
            </div>
            <input type="text" class="check-comment hidden" placeholder="Commentaire" aria-label="Commentaire pour ${escapeHtml(it.label)}"/>
          </div>`
          )
          .join("")}
      </div>`
    : "";

  openModal(
    `
    <div class="modal-header">
      <div class="card-title">Contrôle — ${escapeHtml(tool.name)}</div>
      <button class="btn btn-ghost btn-sm" id="insp-close">Fermer</button>
    </div>
    <form id="insp-form" class="form-grid">
      <p class="card-sub">Périodicité : ${policy.periodicity_days} jours${policy.source === "default" ? " (valeur par défaut, à valider par le responsable sécurité)" : ""}.</p>
      ${checklist}
      <div class="field">
        <label>État constaté (0 à 5)</label>
        <input type="number" name="state" min="0" max="5" value="${tool.state}" required inputmode="numeric"/>
      </div>
      ${
        kind === "agency"
          ? `<div class="field"><label>Statut</label>
              <select name="status">${AGENCY_STATUSES.map(([v, l]) => `<option value="${v}" ${v === status ? "selected" : ""}>${l}</option>`).join("")}</select></div>
            <div class="field hidden" id="loss-field"><label>Motif de perte</label>
              <select name="loss_reason"><option value="casse">Casse</option><option value="vol">Vol</option><option value="perte">Perte</option></select></div>`
          : ""
      }
      <div class="field">
        <label>Commentaire</label>
        <textarea name="comment" rows="2"></textarea>
      </div>
      <div class="field">
        <label>Photo${policy.requires_photo ? " (obligatoire)" : " (optionnel)"}</label>
        <input type="file" name="photo" accept="image/*" capture="environment"/>
      </div>
      ${
        policy.requires_report
          ? `<div class="field"><label>Rapport de vérification (PDF)</label><input type="file" name="report" accept="application/pdf"/></div>`
          : ""
      }
      <button type="submit" class="btn btn-primary btn-block">Enregistrer le contrôle</button>
    </form>
  `,
    {
      onMount: (root) => {
        root.querySelector("#insp-close").addEventListener("click", closeModal);
        const form = root.querySelector("#insp-form");

        form.querySelectorAll(".check-item").forEach((row) => {
          row.querySelectorAll("input[type=radio]").forEach((radio) =>
            radio.addEventListener("change", () => {
              row.querySelector(".check-comment").classList.toggle("hidden", radio.value !== "ko");
            })
          );
        });
        const statusSelect = form.querySelector('[name="status"]');
        if (statusSelect) {
          const toggle = () => root.querySelector("#loss-field").classList.toggle("hidden", statusSelect.value !== "hors_service");
          statusSelect.addEventListener("change", toggle);
          toggle();
        }

        form.addEventListener("submit", async (e) => {
          e.preventDefault();
          const data = new FormData(form);
          const photoFile = data.get("photo");
          const reportFile = data.get("report");
          const answers = [...form.querySelectorAll(".check-item")].map((row) => ({
            id: row.dataset.id,
            answer: (row.querySelector("input[type=radio]:checked") || {}).value || null,
            comment: row.querySelector(".check-comment").value || null,
          }));
          const payload = {
            tool_kind: kind,
            tool_id: tool.id,
            state_after: Number(data.get("state")),
            comment: data.get("comment") || null,
            checklist: answers,
            photo_attached: !!(photoFile && photoFile.size),
          };
          if (kind === "agency") {
            payload.status = data.get("status");
            if (payload.status === "hors_service") payload.loss_reason = data.get("loss_reason");
          }
          try {
            const inspection = await api.post("/inspections", payload);
            if (photoFile && photoFile.size) await api.upload(`/inspections/${inspection.id}/photo`, await compressImage(photoFile));
            if (reportFile && reportFile.size) await api.upload(`/inspections/${inspection.id}/report`, reportFile);
            const label = { conforme: "Contrôle enregistré : conforme", conforme_avec_reserves: "Contrôle enregistré : conforme avec réserves", non_conforme: "Contrôle enregistré : NON conforme" }[inspection.result];
            toast(label, inspection.result === "non_conforme" ? "error" : "success");
            closeModal();
            if (onDone) onDone(inspection);
          } catch (err) {
            toast(err instanceof ApiError ? err.message : "Erreur", "error");
          }
        });
      },
    }
  );
}
