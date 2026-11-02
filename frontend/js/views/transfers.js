import { api, ApiError } from "../api.js";
import {
  escapeHtml,
  formatDate,
  toast,
  openModal,
  closeModal,
} from "../ui.js";
import { state, isAdmin } from "../state.js";
import { getAllUsers, getUserName } from "../usersCache.js";
import { openToolHistory } from "../toolHistory.js";
import { icon } from "../icons.js";
import { openSignaturePad } from "../signaturePad.js";

const TYPE_LABELS = { sous_traitant: "Sous-traitant", interimaire: "Intérimaire", autre: "Autre" };

let currentFilter = "active";

export async function renderTransfers(app) {
  await draw(app);
}

async function draw(app) {
  const transfers = await api.get("/transfers?scope=team");
  await getAllUsers();

  const filtered = currentFilter === "active" ? transfers.filter((t) => t.status === "en_cours") : transfers.filter((t) => t.status === "termine");

  app.innerHTML = `
    <div class="section-header"><h1>Prêts à l'extérieur</h1></div>
    <div class="tag-row" id="tf-filters">
      <button data-f="active" class="${currentFilter === "active" ? "active" : ""}">En cours</button>
      <button data-f="done" class="${currentFilter === "done" ? "active" : ""}">Rendus</button>
    </div>
    <div id="tf-list">
      ${filtered.length ? filtered.map((t) => transferCard(t)).join("") : `<div class="empty-state">Aucun prêt.</div>`}
    </div>
    <button class="fab" id="add-transfer-fab" aria-label="Nouveau prêt externe">${icon("plus", { size: 22 })}</button>
  `;

  document.querySelectorAll("#tf-filters button").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentFilter = btn.dataset.f;
      draw(app);
    });
  });

  document.getElementById("add-transfer-fab").addEventListener("click", () => openTransferForm(() => draw(app)));

  document.querySelectorAll("#tf-list [data-tf-id]").forEach((card) => {
    const id = Number(card.dataset.tfId);
    const transfer = filtered.find((t) => t.id === id);

    card.querySelector('[data-action="history"]').addEventListener("click", () => {
      openToolHistory(transfer.tool_id ? "personal" : "agency", transfer.tool_id || transfer.agency_tool_id, "Prêt externe");
    });

    const returnBtn = card.querySelector('[data-action="return"]');
    if (returnBtn) returnBtn.addEventListener("click", () => openReturnForm(transfer, () => draw(app)));

    card.querySelector('[data-action="discharge"]').addEventListener("click", () =>
      api.download(`/transfers/${transfer.id}/discharge.pdf`, `decharge-${transfer.id}.pdf`).catch((err) => toast(err.message, "error"))
    );
    card.querySelector('[data-action="sign"]').addEventListener("click", () =>
      openSignaturePad(
        "Signature du bénéficiaire",
        async (signature, name) => {
          try {
            await api.post(`/transfers/${transfer.id}/signature`, { signature, signed_name: name });
            toast("Signature enregistrée", "success");
            draw(app);
          } catch (err) {
            toast(err.message, "error");
          }
        },
        transfer.to_external_name
      )
    );
  });
}

function transferCard(t) {
  const canReturn = t.status === "en_cours" && (isAdmin() || t.from_user_id === state.user.id);
  return `
    <div class="card" data-tf-id="${t.id}">
      <div class="card-row">
        <div class="card-title">${t.agency_tool_id ? '<span class="badge badge-blue">Agence</span> ' : ""}Prêt #${t.id}</div>
        <span class="badge ${t.status === "en_cours" ? "badge-orange" : "badge-green"}"><span class="dot"></span>${t.status === "en_cours" ? "En cours" : "Terminé"}</span>
      </div>
      <div class="card-sub">De ${escapeHtml(getUserName(t.from_user_id))} → ${escapeHtml(t.to_external_name)} <span class="badge badge-gray">${TYPE_LABELS[t.to_external_type] || t.to_external_type}</span></div>
      <div class="card-meta">
        ${t.to_external_company ? `<span>Entreprise : ${escapeHtml(t.to_external_company)}</span>` : ""}
        ${t.attached_to_id ? `<span>Rattaché à : ${escapeHtml(getUserName(t.attached_to_id))}</span>` : ""}
        ${t.site_code ? `<span>Chantier : ${escapeHtml(t.site_code)}</span>` : ""}
        ${t.client_code ? `<span>Code client : ${escapeHtml(t.client_code)}</span>` : ""}
        <span>Prêté le : ${formatDate(t.transfer_date)}</span>
        ${t.planned_return_date ? `<span>Retour prévu : ${formatDate(t.planned_return_date)}</span>` : ""}
        ${t.actual_return_date ? `<span>Rendu le : ${formatDate(t.actual_return_date)}</span>` : ""}
      </div>
      ${t.comment ? `<div class="card-sub">${escapeHtml(t.comment)}</div>` : ""}
      ${t.status === "termine" ? `<div class="card-sub">État : ${t.state_before ?? "-"}/5 → ${t.state_after ?? "-"}/5</div>` : ""}
      <div class="card-actions">
        <button class="btn btn-sm" data-action="history">Historique</button>
        <button class="btn btn-sm" data-action="discharge">Décharge (PDF)</button>
        <button class="btn btn-sm" data-action="sign">Signature</button>
        ${canReturn ? '<button class="btn btn-sm" data-action="return">Rendre l\'outil</button>' : ""}
      </div>
    </div>
  `;
}

async function openTransferForm(onDone) {
  const [myTools, agencyTools, users] = await Promise.all([
    api.get("/personal-tools"),
    api.get("/agency-tools"),
    getAllUsers(),
  ]);

  const heldByMe = myTools.filter((t) => t.current_holder_id === state.user.id && t.state_reason === "normal");
  const availableAgency = agencyTools.filter((t) => t.status === "disponible");

  const html = `
    <div class="modal-header">
      <div class="card-title">Nouveau prêt externe</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <form id="transfer-form" class="form-grid">
      <div class="field">
        <label>Outil</label>
        <select name="tool_ref" required>
          <option value="">-</option>
          <optgroup label="Mes outils">
            ${heldByMe.map((t) => `<option value="personal:${t.id}">${escapeHtml(t.name)} (${escapeHtml(t.unique_code)})</option>`).join("")}
          </optgroup>
          <optgroup label="Outils d'agence disponibles">
            ${availableAgency.map((t) => `<option value="agency:${t.id}">${escapeHtml(t.name)} (${escapeHtml(t.unique_code)})</option>`).join("")}
          </optgroup>
        </select>
      </div>
      <div class="field">
        <label>Nom du destinataire</label>
        <input type="text" name="to_external_name" required/>
      </div>
      <div class="field-row">
        <div class="field"><label>Email du bénéficiaire</label><input type="email" name="to_external_email"/></div>
        <div class="field"><label>Téléphone</label><input type="tel" name="to_external_phone"/></div>
      </div>
      <div class="field">
        <label>Type</label>
        <select name="to_external_type" id="tf-type">
          <option value="sous_traitant">Sous-traitant</option>
          <option value="interimaire">Intérimaire</option>
          <option value="autre" selected>Autre</option>
        </select>
      </div>
      <div id="tf-company-fields">
        <div class="field">
          <label>Entreprise</label>
          <input type="text" name="to_external_company"/>
        </div>
        <div class="field">
          <label>Code client</label>
          <input type="text" name="client_code"/>
        </div>
      </div>
      <div class="field hidden" id="tf-attached-field">
        <label>Rattaché à</label>
        <select name="attached_to_id">
          <option value="">-</option>
          ${users.map((u) => `<option value="${u.id}">${escapeHtml(u.full_name)}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label>Code chantier</label>
        <input type="text" name="site_code"/>
      </div>
      <div class="field">
        <label>Date de retour prévue</label>
        <input type="date" name="planned_return_date"/>
      </div>
      <div class="field">
        <label>Commentaire</label>
        <textarea name="comment" rows="2"></textarea>
      </div>
      <button type="submit" class="btn btn-primary">Créer le prêt</button>
    </form>
  `;

  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      const typeSelect = root.querySelector("#tf-type");
      const companyFields = root.querySelector("#tf-company-fields");
      const attachedField = root.querySelector("#tf-attached-field");

      function syncType() {
        const isInterim = typeSelect.value === "interimaire";
        companyFields.classList.toggle("hidden", isInterim);
        attachedField.classList.toggle("hidden", !isInterim);
      }
      typeSelect.addEventListener("change", syncType);
      syncType();

      root.querySelector("#transfer-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        const [refKind, refId] = (data.tool_ref || "").split(":");
        if (!refKind) {
          toast("Choisissez un outil", "error");
          return;
        }
        const payload = {
          tool_id: refKind === "personal" ? Number(refId) : null,
          agency_tool_id: refKind === "agency" ? Number(refId) : null,
          to_external_name: data.to_external_name,
          to_external_type: data.to_external_type,
          to_external_email: data.to_external_email || null,
          to_external_phone: data.to_external_phone || null,
          to_external_company: data.to_external_type === "interimaire" ? null : data.to_external_company || null,
          client_code: data.to_external_type === "interimaire" ? null : data.client_code || null,
          attached_to_id: data.to_external_type === "interimaire" && data.attached_to_id ? Number(data.attached_to_id) : null,
          site_code: data.site_code || null,
          planned_return_date: data.planned_return_date ? new Date(data.planned_return_date).toISOString() : null,
          comment: data.comment || null,
        };
        try {
          await api.post("/transfers", payload);
          toast("Prêt externe créé", "success");
          closeModal();
          onDone();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}

function openReturnForm(transfer, onDone) {
  const html = `
    <div class="modal-header">
      <div class="card-title">Retour du prêt externe</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <form id="return-form" class="form-grid">
      <div class="field">
        <label>État constaté au retour (0-5)</label>
        <input type="number" name="state_after" min="0" max="5" value="${transfer.state_before ?? 5}" required/>
      </div>
      <div class="field">
        <label>Commentaire</label>
        <textarea name="comment" rows="2"></textarea>
      </div>
      <button type="submit" class="btn btn-primary">Confirmer le retour</button>
    </form>
  `;
  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      root.querySelector("#return-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        try {
          await api.post(`/transfers/${transfer.id}/return`, {
            state_after: Number(data.state_after),
            comment: data.comment || null,
          });
          toast("Retour enregistré", "success");
          closeModal();
          onDone();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}
