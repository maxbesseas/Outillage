import { api, ApiError } from "../api.js";
import {
  escapeHtml,
  formatDate,
  stateStars,
  toast,
  openModal,
  closeModal,
  confirmDialog,
} from "../ui.js";
import { state, isAdmin, isManager } from "../state.js";
import { getAllUsers, getUserName } from "../usersCache.js";
import { openToolHistory } from "../toolHistory.js";
import { icon } from "../icons.js";

const CONTROL_MAX_AGE_DAYS = 365;
const WORN_THRESHOLD = 2;

export const EPI_TYPES = [
  "Casque",
  "Harnais",
  "Chaussures de sécurité",
  "Protection auditive",
  "Gants",
  "Lunettes",
  "Tapis isolant",
];

function isOverdue(lastControlDate) {
  if (!lastControlDate) return true;
  const days = (Date.now() - new Date(lastControlDate).getTime()) / 86400000;
  return days > CONTROL_MAX_AGE_DAYS;
}

function isExpired(expirationDate) {
  if (!expirationDate) return false;
  return new Date(expirationDate).getTime() < Date.now();
}

function isWorn(epiItem) {
  return epiItem.state <= WORN_THRESHOLD;
}

export function epiCard(epiItem, options = {}) {
  const canManage = isManager();
  const canPhoto = canManage || epiItem.assigned_to_id === state.user.id;
  const assignedName = epiItem.assigned_to_id ? getUserName(epiItem.assigned_to_id) : "Non assigné";

  return `
    <div class="card" data-epi-id="${epiItem.id}">
      <div class="card-with-thumb">
        ${epiItem.photo_path ? `<img class="thumb" src="${epiItem.photo_path}"/>` : `<div class="thumb"></div>`}
        <div style="flex:1;">
          <div class="card-row">
            <div class="card-title">${escapeHtml(epiItem.name)}</div>
            <div class="state-stars">${stateStars(epiItem.state)}</div>
          </div>
          <div class="card-sub">${escapeHtml([epiItem.type, epiItem.brand].filter(Boolean).join(" · ") || "-")}</div>
          <div class="card-meta">
            <span>Code : ${escapeHtml(epiItem.unique_code)}</span>
            <span>Assigné à : ${escapeHtml(assignedName)}</span>
            <span>Validité : ${formatDate(epiItem.expiration_date)}</span>
            <span>Contrôle : ${formatDate(epiItem.last_control_date)}</span>
            ${isExpired(epiItem.expiration_date) ? '<span class="badge badge-red">Périmé</span>' : ""}
            ${isWorn(epiItem) ? '<span class="badge badge-orange">Usé</span>' : ""}
            ${isOverdue(epiItem.last_control_date) ? '<span class="badge badge-gray">Contrôle à faire</span>' : ""}
          </div>
          ${epiItem.comment ? `<div class="card-sub">${escapeHtml(epiItem.comment)}</div>` : ""}
        </div>
      </div>
      <div class="card-actions">
        <a class="btn btn-sm" href="#/outil/epi/${epiItem.id}">Fiche</a>
        <button class="btn btn-sm" data-epi-action="control">Contrôler</button>
        ${canManage ? '<button class="btn btn-sm" data-epi-action="edit">Modifier</button>' : ""}
        ${canPhoto ? '<button class="btn btn-sm" data-epi-action="photo">Photo</button>' : ""}
        <button class="btn btn-sm" data-epi-action="history">Historique</button>
        ${isAdmin() ? '<button class="btn btn-sm btn-danger" data-epi-action="delete">Supprimer</button>' : ""}
      </div>
    </div>
  `;
}

export function wireEpiCardActions(container, onChanged) {
  container.querySelectorAll("[data-epi-id]").forEach((card) => {
    const id = Number(card.dataset.epiId);

    const controlBtn = card.querySelector('[data-epi-action="control"]');
    if (controlBtn) {
      controlBtn.addEventListener("click", async () => {
        const item = await api.get(`/epi/${id}`);
        openControlForm(item, onChanged);
      });
    }

    const editBtn = card.querySelector('[data-epi-action="edit"]');
    if (editBtn) {
      editBtn.addEventListener("click", async () => {
        const item = await api.get(`/epi/${id}`);
        openEpiForm(item, onChanged);
      });
    }

    const photoBtn = card.querySelector('[data-epi-action="photo"]');
    if (photoBtn) {
      photoBtn.addEventListener("click", async () => {
        const item = await api.get(`/epi/${id}`);
        openPhotoForm(item, onChanged);
      });
    }

    const historyBtn = card.querySelector('[data-epi-action="history"]');
    if (historyBtn) {
      historyBtn.addEventListener("click", () => {
        const name = card.querySelector(".card-title").textContent;
        openToolHistory("epi", id, name);
      });
    }

    const deleteBtn = card.querySelector('[data-epi-action="delete"]');
    if (deleteBtn) {
      deleteBtn.addEventListener("click", async () => {
        if (!(await confirmDialog("Supprimer définitivement cet EPI ?", { danger: true }))) return;
        try {
          await api.delete(`/epi/${id}`);
          toast("EPI supprimé", "success");
          onChanged();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    }
  });
}

function openControlForm(epiItem, onChanged) {
  const html = `
    <div class="modal-header">
      <div class="card-title">Contrôler — ${escapeHtml(epiItem.name)}</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <form id="control-form" class="form-grid">
      <div class="field">
        <label>État constaté (0-5)</label>
        <input type="number" name="state" min="0" max="5" value="${epiItem.state}" required/>
      </div>
      <div class="field">
        <label>Commentaire</label>
        <textarea name="comment" rows="2">${escapeHtml(epiItem.comment || "")}</textarea>
      </div>
      <button type="submit" class="btn btn-primary">Enregistrer</button>
    </form>
  `;
  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      root.querySelector("#control-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        try {
          await api.post(`/epi/${epiItem.id}/control`, {
            state: Number(data.state),
            comment: data.comment || null,
          });
          toast("Contrôle enregistré", "success");
          closeModal();
          onChanged();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}

async function openEpiForm(epiItem, onChanged) {
  const isEdit = !!epiItem;
  let users = [];
  if (isManager()) {
    users = await getAllUsers();
  }

  const typeList = EPI_TYPES.map((t) => `<option value="${escapeHtml(t)}"></option>`).join("");

  const assignedField = isManager()
    ? `
    <div class="field">
      <label>Assigné à</label>
      <select name="assigned_to_id">
        <option value="">Non assigné</option>
        ${users
          .map(
            (u) =>
              `<option value="${u.id}" ${epiItem?.assigned_to_id === u.id ? "selected" : ""}>${escapeHtml(u.full_name)}</option>`
          )
          .join("")}
      </select>
    </div>`
    : `<div class="card-sub">Cet EPI sera enregistré à votre nom.</div>`;

  const html = `
    <div class="modal-header">
      <div class="card-title">${isEdit ? "Modifier l'EPI" : "Ajouter un EPI"}</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <form id="epi-form" class="form-grid">
      <div class="field">
        <label>Nom</label>
        <input type="text" name="name" value="${escapeHtml(epiItem?.name || "")}" required/>
      </div>
      <div class="field">
        <label>Type</label>
        <input type="text" name="type" list="epi-type-list" value="${escapeHtml(epiItem?.type || "")}"/>
        <datalist id="epi-type-list">${typeList}</datalist>
      </div>
      <div class="field">
        <label>Marque</label>
        <input type="text" name="brand" value="${escapeHtml(epiItem?.brand || "")}"/>
      </div>
      <div class="field">
        <label>Code unique</label>
        <input type="text" name="unique_code" value="${escapeHtml(epiItem?.unique_code || "")}" required/>
      </div>
      <div class="field">
        <label>Date de validité</label>
        <input type="date" name="expiration_date" value="${epiItem?.expiration_date ? epiItem.expiration_date.slice(0, 10) : ""}"/>
      </div>
      <div class="field">
        <label>État (0-5)</label>
        <input type="number" name="state" min="0" max="5" value="${epiItem?.state ?? 5}"/>
      </div>
      ${assignedField}
      <div class="field">
        <label>Commentaire</label>
        <textarea name="comment" rows="2">${escapeHtml(epiItem?.comment || "")}</textarea>
      </div>
      <button type="submit" class="btn btn-primary">${isEdit ? "Enregistrer" : "Ajouter"}</button>
    </form>
  `;

  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      root.querySelector("#epi-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        const payload = {
          name: data.name,
          type: data.type || null,
          brand: data.brand || null,
          unique_code: data.unique_code,
          expiration_date: data.expiration_date ? new Date(data.expiration_date).toISOString() : null,
          state: Number(data.state),
          comment: data.comment || null,
        };
        if (isManager()) {
          payload.assigned_to_id = data.assigned_to_id ? Number(data.assigned_to_id) : null;
        }
        try {
          if (isEdit) {
            await api.patch(`/epi/${epiItem.id}`, payload);
          } else {
            await api.post("/epi", payload);
          }
          toast(isEdit ? "EPI mis à jour" : "EPI ajouté", "success");
          closeModal();
          onChanged();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}

function openPhotoForm(epiItem, onChanged) {
  const html = `
    <div class="modal-header">
      <div class="card-title">Photo — ${escapeHtml(epiItem.name)}</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    ${epiItem.photo_path ? `<img src="${epiItem.photo_path}" style="max-width:100%;border-radius:7px;margin-bottom:1rem;"/>` : ""}
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
          await api.upload(`/epi/${epiItem.id}/photo`, file);
          toast("Photo enregistrée", "success");
          closeModal();
          onChanged();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}

export { openEpiForm };

let currentTab = "all";

export async function renderEpi(app) {
  await draw(app);
}

async function draw(app) {
  const [epiList] = await Promise.all([api.get("/epi")]);
  await getAllUsers();

  const flagged = epiList.filter((e) => isExpired(e.expiration_date) || isWorn(e));

  const searchInput = app.querySelector?.("#epi-search")?.value || "";
  const typeFilter = app.querySelector?.("#epi-type-filter")?.value || "";
  const assignedFilter = app.querySelector?.("#epi-assigned-filter")?.value || "";

  const types = [...new Set(epiList.map((e) => e.type).filter(Boolean))].sort();
  const assignedIds = [...new Set(epiList.map((e) => e.assigned_to_id).filter(Boolean))];

  let filtered = epiList;
  if (currentTab === "watch") filtered = filtered.filter((e) => isExpired(e.expiration_date) || isWorn(e));
  if (currentTab === "control") filtered = filtered.filter((e) => isOverdue(e.last_control_date));

  if (searchInput) {
    const q = searchInput.toLowerCase();
    filtered = filtered.filter((e) => e.name.toLowerCase().includes(q) || e.unique_code.toLowerCase().includes(q));
  }
  if (typeFilter) filtered = filtered.filter((e) => e.type === typeFilter);
  if (assignedFilter) filtered = filtered.filter((e) => e.assigned_to_id === Number(assignedFilter));

  app.innerHTML = `
    <div class="section-header"><h1>EPI</h1></div>

    ${
      flagged.length
        ? `
      <div class="alert-block">
        <strong>À surveiller</strong>
        <div class="card-meta" style="margin-top:0.5rem;">
          ${flagged
            .slice(0, 8)
            .map((e) => `<span class="badge badge-red">${escapeHtml(e.name)}</span>`)
            .join("")}
          ${flagged.length > 8 ? `<span>+${flagged.length - 8} autres</span>` : ""}
        </div>
      </div>`
        : ""
    }

    <div class="filter-bar">
      <input type="text" id="epi-search" placeholder="Recherche nom/code" value="${escapeHtml(searchInput)}"/>
      <select id="epi-type-filter">
        <option value="">Tous types</option>
        ${types.map((t) => `<option value="${escapeHtml(t)}" ${t === typeFilter ? "selected" : ""}>${escapeHtml(t)}</option>`).join("")}
      </select>
      <select id="epi-assigned-filter">
        <option value="">Toutes personnes</option>
        ${assignedIds
          .map((id) => `<option value="${id}" ${String(id) === assignedFilter ? "selected" : ""}>${escapeHtml(getUserName(id))}</option>`)
          .join("")}
      </select>
    </div>

    <div class="tag-row" id="epi-tabs">
      <button data-tab="all" class="${currentTab === "all" ? "active" : ""}">Tous</button>
      <button data-tab="watch" class="${currentTab === "watch" ? "active" : ""}">À surveiller</button>
      <button data-tab="control" class="${currentTab === "control" ? "active" : ""}">À contrôler</button>
    </div>

    <div id="epi-list">
      ${filtered.length ? filtered.map((e) => epiCard(e)).join("") : `<div class="empty-state">Aucun EPI.</div>`}
    </div>
    <button class="fab" id="add-epi-fab" aria-label="Ajouter un EPI">${icon("plus", { size: 22 })}</button>
  `;

  document.querySelectorAll("#epi-tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentTab = btn.dataset.tab;
      draw(app);
    });
  });

  ["epi-search", "epi-type-filter", "epi-assigned-filter"].forEach((id) => {
    const el = document.getElementById(id);
    el.addEventListener(id === "epi-search" ? "input" : "change", () => draw(app));
  });

  document.getElementById("add-epi-fab").addEventListener("click", () => openEpiForm(null, () => draw(app)));

  wireEpiCardActions(document.getElementById("epi-list"), () => draw(app));
}
