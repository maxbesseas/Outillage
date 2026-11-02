import { api, ApiError } from "../api.js";
import {
  escapeHtml,
  formatDate,
  stateStars,
  stateReasonBadge,
  toast,
  openModal,
  closeModal,
  confirmDialog,
} from "../ui.js";
import { state, isAdmin } from "../state.js";
import { getTeam } from "../usersCache.js";
import { openToolHistory } from "../toolHistory.js";
import { navigate } from "../router.js";
import { icon } from "../icons.js";
import { TYPE_CATEGORIES, wireTypeAutocomplete } from "../toolTypeSuggestions.js";

const CONTROL_MAX_AGE_DAYS = 365;
const WARRANTY_YEARS = [1, 2, 3, 5];

function isOverdue(lastControlDate) {
  if (!lastControlDate) return true;
  const days = (Date.now() - new Date(lastControlDate).getTime()) / 86400000;
  return days > CONTROL_MAX_AGE_DAYS;
}

let currentFilter = "all";
let currentOwnerId = null;

export async function renderPersonalTools(app, params) {
  currentOwnerId = params && params.id ? Number(params.id) : null;
  await draw(app);
}

async function draw(app) {
  const isTeamView = currentOwnerId !== null;
  const ownerId = isTeamView ? currentOwnerId : state.user.id;

  let team = [];
  if (isTeamView || true) {
    try {
      team = await getTeam();
    } catch {
      team = [];
    }
  }

  const tools = await api.get(`/personal-tools?owner_id=${ownerId}`);
  const filtered = currentFilter === "overdue" ? tools.filter((t) => isOverdue(t.last_control_date)) : tools;

  const teamSelect = isTeamView
    ? `
    <div class="field" style="max-width:280px;margin-bottom:1rem;">
      <label>Salarié</label>
      <select id="team-select">
        ${team
          .map((u) => `<option value="${u.id}" ${u.id === ownerId ? "selected" : ""}>${escapeHtml(u.full_name)}</option>`)
          .join("")}
      </select>
    </div>`
    : "";

  app.innerHTML = `
    <div class="section-header">
      <h1>${isTeamView ? "Outils du salarié" : "Mes outils"}</h1>
    </div>
    ${teamSelect}
    <div class="tag-row" id="tool-filters">
      <button data-filter="all" class="${currentFilter === "all" ? "active" : ""}">Tous</button>
      <button data-filter="overdue" class="${currentFilter === "overdue" ? "active" : ""}">À contrôler</button>
    </div>
    <div id="tool-list">
      ${filtered.length ? filtered.map((t) => toolCard(t, ownerId)).join("") : `<div class="empty-state">Aucun outil.</div>`}
    </div>
    <button class="fab" id="add-tool-fab">${icon("plus", { size: 22 })}</button>
  `;

  if (isTeamView) {
    document.getElementById("team-select").addEventListener("change", (e) => {
      navigate(`/salaries/${e.target.value}`);
    });
  }

  document.querySelectorAll("#tool-filters button").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentFilter = btn.dataset.filter;
      draw(app);
    });
  });

  document.getElementById("add-tool-fab").addEventListener("click", () => openToolForm(null, app));

  wireCardActions(app);
}

function toolCard(t, ownerId) {
  const heldByOther = t.current_holder_id && t.current_holder_id !== t.owner_id;
  return `
    <div class="card" data-id="${t.id}">
      <div class="card-with-thumb">
        ${t.photo_path ? `<img class="thumb" src="${t.photo_path}"/>` : `<div class="thumb"></div>`}
        <div style="flex:1;">
          <div class="card-row">
            <div class="card-title">${escapeHtml(t.name)}</div>
            <div class="state-stars">${stateStars(t.state)}</div>
          </div>
          <div class="card-sub">${escapeHtml([t.type, t.brand, t.model].filter(Boolean).join(" · ") || "-")}</div>
          <div class="card-meta">
            <span>Code : ${escapeHtml(t.unique_code)}</span>
            <span>Achat : ${formatDate(t.purchase_date)}</span>
            <span>Contrôle : ${formatDate(t.last_control_date)}</span>
            ${t.state_reason !== "normal" ? stateReasonBadge(t.state_reason) : ""}
            ${heldByOther ? '<span class="badge badge-blue">Prêté</span>' : ""}
            ${isOverdue(t.last_control_date) ? '<span class="badge badge-orange">Contrôle à faire</span>' : ""}
          </div>
        </div>
      </div>
      <div class="card-actions">
        <a class="btn btn-sm" href="#/outil/personal/${t.id}">Fiche</a>
        <button class="btn btn-sm" data-action="edit">Modifier</button>
        <button class="btn btn-sm" data-action="state">Changer l'état</button>
        <button class="btn btn-sm" data-action="photo">Photo</button>
        <button class="btn btn-sm" data-action="history">Historique</button>
        ${t.owner_id === state.user.id || isAdmin() ? '<button class="btn btn-sm btn-danger" data-action="delete">Supprimer</button>' : ""}
      </div>
    </div>
  `;
}

function wireCardActions(app) {
  app.querySelectorAll("#tool-list .card").forEach((card) => {
    const id = Number(card.dataset.id);
    card.querySelector('[data-action="edit"]').addEventListener("click", async () => {
      const tool = await api.get(`/personal-tools/${id}`);
      openToolForm(tool, app);
    });
    card.querySelector('[data-action="state"]').addEventListener("click", async () => {
      const tool = await api.get(`/personal-tools/${id}`);
      openStateForm(tool, app);
    });
    card.querySelector('[data-action="photo"]').addEventListener("click", async () => {
      const tool = await api.get(`/personal-tools/${id}`);
      openPhotoForm(tool, app);
    });
    card.querySelector('[data-action="history"]').addEventListener("click", () => {
      const name = card.querySelector(".card-title").textContent;
      openToolHistory("personal", id, name);
    });
    const deleteBtn = card.querySelector('[data-action="delete"]');
    if (deleteBtn) {
      deleteBtn.addEventListener("click", async () => {
        if (!(await confirmDialog("Supprimer définitivement cet outil ?", { danger: true }))) return;
        try {
          await api.delete(`/personal-tools/${id}`);
          toast("Outil supprimé", "success");
          draw(app);
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    }
  });
}

function warrantyOptionsHtml() {
  return WARRANTY_YEARS.map((y) => `<option value="${y}">${y} an${y > 1 ? "s" : ""}</option>`).join("");
}

function openToolForm(tool, app) {
  const isEdit = !!tool;
  const typeList = TYPE_CATEGORIES.map((t) => `<option value="${escapeHtml(t)}"></option>`).join("");

  const html = `
    <div class="modal-header">
      <div class="card-title">${isEdit ? "Modifier l'outil" : "Ajouter un outil"}</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <form id="tool-form" class="form-grid">
      <div class="field">
        <label>Nom</label>
        <input type="text" name="name" list="type-name-list" value="${escapeHtml(tool?.name || "")}" required/>
      </div>
      <div class="field">
        <label>Type</label>
        <input type="text" name="type" list="type-cat-list" value="${escapeHtml(tool?.type || "")}"/>
        <datalist id="type-cat-list">${typeList}</datalist>
      </div>
      <div class="field-row">
        <div class="field">
          <label>Marque</label>
          <input type="text" name="brand" value="${escapeHtml(tool?.brand || "")}"/>
        </div>
        <div class="field">
          <label>Modèle</label>
          <input type="text" name="model" value="${escapeHtml(tool?.model || "")}"/>
        </div>
      </div>
      <div class="field">
        <label>Code unique</label>
        <input type="text" name="unique_code" value="${escapeHtml(tool?.unique_code || "")}" required/>
      </div>
      <div class="field-row">
        <div class="field">
          <label>Date d'achat</label>
          <input type="date" name="purchase_date" value="${tool?.purchase_date ? tool.purchase_date.slice(0, 10) : ""}"/>
        </div>
        <div class="field">
          <label>Prix d'achat</label>
          <input type="number" step="0.01" min="0" name="purchase_price" value="${tool?.purchase_price ?? ""}"/>
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label>Durée de garantie</label>
          <select id="warranty-years">
            <option value="">-</option>
            ${warrantyOptionsHtml()}
          </select>
        </div>
        <div class="field">
          <label>Fin de garantie</label>
          <input type="date" name="warranty_expiration_date" value="${tool?.warranty_expiration_date ? tool.warranty_expiration_date.slice(0, 10) : ""}"/>
        </div>
      </div>
      <div class="field-row">
        <div class="field">
          <label>Dernier contrôle</label>
          <input type="date" name="last_control_date" value="${tool?.last_control_date ? tool.last_control_date.slice(0, 10) : ""}"/>
        </div>
        <div class="field">
          <label>État (0-5)</label>
          <input type="number" name="state" min="0" max="5" value="${tool?.state ?? 5}"/>
        </div>
      </div>
      <button type="submit" class="btn btn-primary">${isEdit ? "Enregistrer" : "Ajouter"}</button>
    </form>
  `;

  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      const form = root.querySelector("#tool-form");
      const nameInput = form.querySelector('[name="name"]');
      const typeInput = form.querySelector('[name="type"]');
      wireTypeAutocomplete(nameInput, typeInput);

      const purchaseInput = form.querySelector('[name="purchase_date"]');
      const warrantySelect = root.querySelector("#warranty-years");
      const warrantyDateInput = form.querySelector('[name="warranty_expiration_date"]');

      function recalcWarranty() {
        const years = Number(warrantySelect.value);
        if (!years || !purchaseInput.value) return;
        const d = new Date(purchaseInput.value);
        d.setFullYear(d.getFullYear() + years);
        warrantyDateInput.value = d.toISOString().slice(0, 10);
      }
      warrantySelect.addEventListener("change", recalcWarranty);
      purchaseInput.addEventListener("change", recalcWarranty);

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(form).entries());
        const payload = {
          name: data.name,
          type: data.type || null,
          brand: data.brand || null,
          model: data.model || null,
          unique_code: data.unique_code,
          purchase_date: data.purchase_date ? new Date(data.purchase_date).toISOString() : null,
          purchase_price: data.purchase_price !== "" ? Number(data.purchase_price) : null,
          warranty_expiration_date: data.warranty_expiration_date ? new Date(data.warranty_expiration_date).toISOString() : null,
          last_control_date: data.last_control_date ? new Date(data.last_control_date).toISOString() : null,
          state: Number(data.state),
        };
        try {
          if (isEdit) {
            await api.patch(`/personal-tools/${tool.id}`, payload);
          } else {
            await api.post("/personal-tools", payload);
          }
          toast(isEdit ? "Outil mis à jour" : "Outil ajouté", "success");
          closeModal();
          draw(document.getElementById("app"));
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}

function openStateForm(tool, app) {
  const html = `
    <div class="modal-header">
      <div class="card-title">Changer l'état — ${escapeHtml(tool.name)}</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <form id="state-form" class="form-grid">
      <div class="field">
        <label>Nouvel état (0-5)</label>
        <input type="number" name="state" min="0" max="5" value="${tool.state}" required/>
      </div>
      <div class="field">
        <label>Motif</label>
        <select name="state_reason">
          <option value="normal" ${tool.state_reason === "normal" ? "selected" : ""}>Normal</option>
          <option value="perdu" ${tool.state_reason === "perdu" ? "selected" : ""}>Perdu</option>
          <option value="endommage" ${tool.state_reason === "endommage" ? "selected" : ""}>Endommagé</option>
          <option value="en_reparation" ${tool.state_reason === "en_reparation" ? "selected" : ""}>En réparation</option>
        </select>
      </div>
      <div class="field">
        <label>Commentaire</label>
        <textarea name="state_comment" rows="2">${escapeHtml(tool.state_comment || "")}</textarea>
      </div>
      <div class="field">
        <label>Photo de la casse (optionnel)</label>
        <input type="file" name="photo" accept="image/*" capture="environment"/>
      </div>
      <button type="submit" class="btn btn-primary">Enregistrer</button>
    </form>
  `;

  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      const form = root.querySelector("#state-form");
      const stateInput = form.querySelector('[name="state"]');
      const reasonSelect = form.querySelector('[name="state_reason"]');

      stateInput.addEventListener("input", () => {
        const value = Number(stateInput.value);
        if (value === 0) reasonSelect.value = "endommage";
        else if (value === 1) reasonSelect.value = "en_reparation";
      });

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(form).entries());
        try {
          await api.patch(`/personal-tools/${tool.id}/state`, {
            state: Number(data.state),
            state_reason: data.state_reason,
            state_comment: data.state_comment || null,
          });
          const fileInput = form.querySelector('[name="photo"]');
          if (fileInput.files[0]) {
            await api.upload(`/personal-tools/${tool.id}/state-photo`, fileInput.files[0]);
          }
          toast("État mis à jour", "success");
          closeModal();
          draw(document.getElementById("app"));
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}

function openPhotoForm(tool, app) {
  const html = `
    <div class="modal-header">
      <div class="card-title">Photo — ${escapeHtml(tool.name)}</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    ${tool.photo_path ? `<img src="${tool.photo_path}" style="max-width:100%;border-radius:7px;margin-bottom:1rem;"/>` : ""}
    <form id="photo-form" class="form-grid">
      <div class="field">
        <label>Nouvelle photo</label>
        <input type="file" name="photo" accept="image/*" capture="environment" required/>
      </div>
      <button type="submit" class="btn btn-primary">Enregistrer</button>
    </form>
  `;

  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      root.querySelector("#photo-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const file = root.querySelector('[name="photo"]').files[0];
        if (!file) return;
        try {
          await api.upload(`/personal-tools/${tool.id}/photo`, file);
          toast("Photo enregistrée", "success");
          closeModal();
          draw(document.getElementById("app"));
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}
