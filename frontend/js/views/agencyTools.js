import { api, ApiError } from "../api.js";
import {
  escapeHtml,
  formatDate,
  stateStars,
  agencyStatusBadge,
  toast,
  openModal,
  closeModal,
  confirmDialog,
} from "../ui.js";
import { isAdmin, isManager } from "../state.js";
import { getAllUsers, getUserName } from "../usersCache.js";
import { openToolHistory } from "../toolHistory.js";
import { openReserveForm } from "../reservationForm.js";
import { icon } from "../icons.js";
import { TYPE_CATEGORIES, wireTypeAutocomplete } from "../toolTypeSuggestions.js";
import { epiCard, wireEpiCardActions, openEpiForm } from "./epi.js";

const CONTROL_MAX_AGE_DAYS = 365;
const WARRANTY_YEARS = [1, 2, 3, 5];
const LOSS_REASONS = { vol: "Vol", casse: "Casse", perte: "Perte" };

const PAGE_SIZE = 50;

let currentCategory = "all";
let filters = { q: "", type: "", status: "", lossReason: "" };

function isOverdue(lastControlDate) {
  if (!lastControlDate) return true;
  const days = (Date.now() - new Date(lastControlDate).getTime()) / 86400000;
  return days > CONTROL_MAX_AGE_DAYS;
}

function toolsQuery(limit, offset) {
  const params = new URLSearchParams({ limit, offset });
  if (filters.q) params.set("q", filters.q);
  if (filters.type) params.set("type", filters.type);
  if (filters.status) params.set("status", filters.status);
  if (filters.lossReason) params.set("loss_reason", filters.lossReason);
  return params.toString();
}

function epiQuery(limit, offset) {
  const params = new URLSearchParams({ limit, offset });
  if (filters.q) params.set("q", filters.q);
  if (filters.type) params.set("type", filters.type);
  return params.toString();
}

function epiVisible() {
  const wantsEpi = currentCategory === "all" || currentCategory === "epi";
  return wantsEpi && !filters.status && !filters.lossReason;
}

function toolsVisible() {
  return currentCategory === "all" || currentCategory === "tools";
}

export async function renderAgencyTools(app) {
  await getAllUsers();
  const [toolTypes, epiTypes] = await Promise.all([api.get("/agency-tools/types"), api.get("/epi/types")]);

  const types =
    currentCategory === "tools"
      ? toolTypes
      : currentCategory === "epi"
        ? epiTypes
        : [...new Set([...toolTypes, ...epiTypes])].sort();
  if (filters.type && !types.includes(filters.type)) filters.type = "";

  app.innerHTML = `
    <div class="section-header">
      <h1>Agence — Outillage &amp; EPI</h1>
      <div class="section-links">
        ${isManager() ? '<a href="#/garanties">Garanties</a>' : ""}
        <button class="btn btn-sm" id="export-btn">Exporter en Excel</button>
      </div>
    </div>

    <div class="tag-row" id="cat-tabs">
      <button data-cat="all" class="${currentCategory === "all" ? "active" : ""}">Tous</button>
      <button data-cat="tools" class="${currentCategory === "tools" ? "active" : ""}">Outillage</button>
      <button data-cat="epi" class="${currentCategory === "epi" ? "active" : ""}">EPI</button>
    </div>

    <div class="filter-bar">
      <input type="search" id="f-q" placeholder="Recherche" value="${escapeHtml(filters.q)}"/>
      <select id="f-type">
        <option value="">Tous types</option>
        ${types.map((t) => `<option value="${escapeHtml(t)}" ${t === filters.type ? "selected" : ""}>${escapeHtml(t)}</option>`).join("")}
      </select>
      ${
        currentCategory !== "epi"
          ? `
      <select id="f-status">
        <option value="">Tous statuts</option>
        <option value="disponible" ${filters.status === "disponible" ? "selected" : ""}>Disponible</option>
        <option value="emprunte" ${filters.status === "emprunte" ? "selected" : ""}>Emprunté</option>
        <option value="reparation" ${filters.status === "reparation" ? "selected" : ""}>En réparation</option>
        <option value="hors_service" ${filters.status === "hors_service" ? "selected" : ""}>Hors service</option>
        <option value="dotation" ${filters.status === "dotation" ? "selected" : ""}>Dotation</option>
      </select>`
          : ""
      }
      <select id="f-loss" class="${filters.status === "hors_service" ? "" : "hidden"}">
        <option value="">Tout motif</option>
        ${Object.entries(LOSS_REASONS)
          .map(([k, v]) => `<option value="${k}" ${filters.lossReason === k ? "selected" : ""}>${v}</option>`)
          .join("")}
      </select>
      <button class="btn btn-sm" id="reset-filters">Réinitialiser</button>
    </div>
    <div class="filter-count" id="items-count"></div>

    <div id="items-list"></div>
    <div class="load-more"><button class="btn" id="load-more">Charger plus</button></div>

    ${
      isManager()
        ? `
      <div id="fab-menu" class="fab-menu hidden">
        <button class="btn btn-primary" id="add-tool-btn">+ Outil</button>
        <button class="btn btn-primary" id="add-epi-btn">+ EPI</button>
      </div>
      <button class="fab" id="add-fab" aria-label="Ajouter">${icon("plus", { size: 22 })}</button>`
        : ""
    }
  `;

  const list = document.getElementById("items-list");
  const countEl = document.getElementById("items-count");
  const moreBtn = document.getElementById("load-more");

  let toolItems = [];
  let epiItems = [];
  let toolsTotal = 0;
  let epiTotal = 0;
  let requestId = 0;

  function paint() {
    const html =
      (toolsVisible() ? toolItems.map((t) => toolCard(t)).join("") : "") +
      (epiVisible() ? epiItems.map((e) => epiCard(e)).join("") : "");
    const shown = (toolsVisible() ? toolItems.length : 0) + (epiVisible() ? epiItems.length : 0);
    const total = (toolsVisible() ? toolsTotal : 0) + (epiVisible() ? epiTotal : 0);

    list.innerHTML = html || `<div class="empty-state">Aucun élément.</div>`;
    countEl.textContent = `${shown} / ${total} éléments`;
    moreBtn.classList.toggle("hidden", shown >= total);

    wireToolCardActions(list, reloadCurrent);
    wireEpiCardActions(list, reloadCurrent);
  }

  async function fetchSlices(toolLimit, toolOffset, epiLimit, epiOffset) {
    const [toolsPage, epiPage] = await Promise.all([
      toolsVisible() ? api.getPage(`/agency-tools?${toolsQuery(toolLimit, toolOffset)}`) : { items: [], total: 0 },
      epiVisible() ? api.getPage(`/epi?${epiQuery(epiLimit, epiOffset)}`) : { items: [], total: 0 },
    ]);
    return { toolsPage, epiPage };
  }

  async function reload(limitTools, limitEpi) {
    const id = ++requestId;
    try {
      const { toolsPage, epiPage } = await fetchSlices(limitTools, 0, limitEpi, 0);
      if (id !== requestId) return;
      toolItems = toolsPage.items;
      epiItems = epiPage.items;
      toolsTotal = toolsPage.total;
      epiTotal = epiPage.total;
      paint();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur de chargement", "error");
    }
  }

  const reloadFirstPage = () => reload(PAGE_SIZE, PAGE_SIZE);
  function reloadCurrent() {
    return reload(Math.max(PAGE_SIZE, toolItems.length), Math.max(PAGE_SIZE, epiItems.length));
  }

  moreBtn.addEventListener("click", async () => {
    const id = ++requestId;
    moreBtn.disabled = true;
    try {
      const { toolsPage, epiPage } = await fetchSlices(PAGE_SIZE, toolItems.length, PAGE_SIZE, epiItems.length);
      if (id !== requestId) return;
      toolItems = toolItems.concat(toolsPage.items);
      epiItems = epiItems.concat(epiPage.items);
      toolsTotal = toolsPage.total;
      epiTotal = epiPage.total;
      paint();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur de chargement", "error");
    } finally {
      moreBtn.disabled = false;
    }
  });

  document.querySelectorAll("#cat-tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentCategory = btn.dataset.cat;
      if (currentCategory === "epi") {
        filters.status = "";
        filters.lossReason = "";
      }
      renderAgencyTools(app);
    });
  });

  let searchTimer = null;
  document.getElementById("f-q").addEventListener("input", (e) => {
    filters.q = e.target.value.trim();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(reloadFirstPage, 300);
  });
  document.getElementById("f-type").addEventListener("change", (e) => {
    filters.type = e.target.value;
    reloadFirstPage();
  });
  const statusSelect = document.getElementById("f-status");
  const lossSelect = document.getElementById("f-loss");
  if (statusSelect) {
    statusSelect.addEventListener("change", (e) => {
      filters.status = e.target.value;
      if (filters.status !== "hors_service") {
        filters.lossReason = "";
        lossSelect.value = "";
      }
      lossSelect.classList.toggle("hidden", filters.status !== "hors_service");
      reloadFirstPage();
    });
  }
  lossSelect.addEventListener("change", (e) => {
    filters.lossReason = e.target.value;
    reloadFirstPage();
  });
  document.getElementById("reset-filters").addEventListener("click", () => {
    filters = { q: "", type: "", status: "", lossReason: "" };
    renderAgencyTools(app);
  });

  document.getElementById("export-btn").addEventListener("click", () => {
    api.download("/agency-tools/export", "Outillage.xlsx").catch((err) => {
      toast(err instanceof ApiError ? err.message : "Erreur export", "error");
    });
  });

  const fab = document.getElementById("add-fab");
  if (fab) {
    const menu = document.getElementById("fab-menu");
    fab.addEventListener("click", () => menu.classList.toggle("hidden"));
    document.getElementById("add-tool-btn").addEventListener("click", () => {
      menu.classList.add("hidden");
      openToolForm(null, reloadCurrent);
    });
    document.getElementById("add-epi-btn").addEventListener("click", () => {
      menu.classList.add("hidden");
      openEpiForm(null, reloadCurrent);
    });
  }

  await reloadFirstPage();
}

function toolCard(t) {
  return `
    <div class="card" data-tool-id="${t.id}">
      <div class="card-with-thumb">
        ${t.photo_path ? `<img class="thumb" src="${t.photo_path}"/>` : `<div class="thumb"></div>`}
        <div style="flex:1;">
          <div class="card-row">
            <div class="card-title">${escapeHtml(t.name)}</div>
            <div class="state-stars">${stateStars(t.state)}</div>
          </div>
          <div class="card-sub">${escapeHtml([t.type, t.brand].filter(Boolean).join(" · ") || "-")}</div>
          <div class="card-meta">
            ${agencyStatusBadge(t.status)}
            <span>Code : ${escapeHtml(t.unique_code)}</span>
            ${isManager() ? `<span>Achat : ${formatDate(t.purchase_date)} · ${t.purchase_price ?? 0} €</span>` : ""}
            ${t.status === "hors_service" && t.loss_reason ? `<span class="badge badge-red">${LOSS_REASONS[t.loss_reason] || t.loss_reason}</span>` : ""}
            ${t.status === "dotation" ? `<span class="badge badge-blue">Dotation · ${escapeHtml(getUserName(t.assigned_to_id))}</span>` : ""}
            ${isOverdue(t.last_control_date) ? '<span class="badge badge-orange">Contrôle à faire</span>' : ""}
          </div>
        </div>
      </div>
      <div class="card-actions">
        <a class="btn btn-sm" href="#/outil/agency/${t.id}">Fiche</a>
        ${t.status === "disponible" ? '<button class="btn btn-sm" data-tool-action="reserve">Réserver</button>' : ""}
        <button class="btn btn-sm" data-tool-action="history">Historique</button>
        ${isManager() ? '<button class="btn btn-sm" data-tool-action="edit">Modifier</button>' : ""}
        ${isManager() ? '<button class="btn btn-sm" data-tool-action="photo">Photo</button>' : ""}
        ${isAdmin() ? '<button class="btn btn-sm btn-danger" data-tool-action="delete">Supprimer</button>' : ""}
      </div>
    </div>
  `;
}

function wireToolCardActions(container, onChanged) {
  container.querySelectorAll("[data-tool-id]").forEach((card) => {
    const id = Number(card.dataset.toolId);

    const reserveBtn = card.querySelector('[data-tool-action="reserve"]');
    if (reserveBtn) {
      reserveBtn.addEventListener("click", async () => {
        const tool = await api.get(`/agency-tools/${id}`);
        openReserveForm(tool, onChanged);
      });
    }

    card.querySelector('[data-tool-action="history"]').addEventListener("click", async () => {
      const name = card.querySelector(".card-title").textContent;
      openToolHistory("agency", id, name);
    });

    const editBtn = card.querySelector('[data-tool-action="edit"]');
    if (editBtn) {
      editBtn.addEventListener("click", async () => {
        const tool = await api.get(`/agency-tools/${id}`);
        openToolForm(tool, onChanged);
      });
    }

    const photoBtn = card.querySelector('[data-tool-action="photo"]');
    if (photoBtn) {
      photoBtn.addEventListener("click", async () => {
        const tool = await api.get(`/agency-tools/${id}`);
        openPhotoForm(tool, onChanged);
      });
    }

    const deleteBtn = card.querySelector('[data-tool-action="delete"]');
    if (deleteBtn) {
      deleteBtn.addEventListener("click", async () => {
        if (!(await confirmDialog("Supprimer définitivement cet outil ?", { danger: true }))) return;
        try {
          await api.delete(`/agency-tools/${id}`);
          toast("Outil supprimé", "success");
          onChanged();
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

async function openToolForm(tool, onChanged) {
  const isEdit = !!tool;
  const typeList = TYPE_CATEGORIES.map((t) => `<option value="${escapeHtml(t)}"></option>`).join("");
  let users = [];
  if (isEdit) users = await getAllUsers();

  const editOnlyFields = isEdit
    ? `
      <div class="field">
        <label>Statut</label>
        <select name="status">
          <option value="disponible" ${tool.status === "disponible" ? "selected" : ""}>Disponible</option>
          <option value="emprunte" ${tool.status === "emprunte" ? "selected" : ""}>Emprunté</option>
          <option value="reparation" ${tool.status === "reparation" ? "selected" : ""}>En réparation</option>
          <option value="hors_service" ${tool.status === "hors_service" ? "selected" : ""}>Hors service</option>
          <option value="dotation" ${tool.status === "dotation" ? "selected" : ""}>Dotation</option>
        </select>
      </div>
      <div class="field" id="loss-reason-field" style="${tool.status === "hors_service" ? "" : "display:none;"}">
        <label>Motif de perte</label>
        <select name="loss_reason">
          <option value="">-</option>
          ${Object.entries(LOSS_REASONS)
            .map(([k, v]) => `<option value="${k}" ${tool.loss_reason === k ? "selected" : ""}>${v}</option>`)
            .join("")}
        </select>
      </div>
      <div class="field" id="assigned-field" style="${tool.status === "dotation" ? "" : "display:none;"}">
        <label>Assigné à</label>
        <select name="assigned_to_id">
          <option value="">-</option>
          ${users
            .map((u) => `<option value="${u.id}" ${tool.assigned_to_id === u.id ? "selected" : ""}>${escapeHtml(u.full_name)}</option>`)
            .join("")}
        </select>
      </div>
    `
    : "";

  const html = `
    <div class="modal-header">
      <div class="card-title">${isEdit ? "Modifier l'outil" : "Ajouter un outil"}</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <form id="tool-form" class="form-grid">
      ${!isEdit ? `<div class="field"><label>Remplir depuis une photo (optionnel)</label>
        <input type="file" id="ai-photo-input" accept="image/jpeg,image/png,image/webp" capture="environment"/>
        <span class="card-sub" id="ai-photo-status"></span></div>` : ""}
      <div class="field">
        <label>Nom</label>
        <input type="text" name="name" value="${escapeHtml(tool?.name || "")}" required/>
      </div>
      <div class="field">
        <label>Type</label>
        <input type="text" name="type" list="type-cat-list" value="${escapeHtml(tool?.type || "")}"/>
        <datalist id="type-cat-list">${typeList}</datalist>
      </div>
      <div class="field">
        <label>Description</label>
        <textarea name="description" rows="2">${escapeHtml(tool?.description || "")}</textarea>
      </div>
      <div class="field-row">
        <div class="field">
          <label>Marque</label>
          <input type="text" name="brand" value="${escapeHtml(tool?.brand || "")}"/>
        </div>
        <div class="field">
          <label>Code unique</label>
          <input type="text" name="unique_code" value="${escapeHtml(tool?.unique_code || "")}" required/>
        </div>
      </div>
      <div class="field">
        <label>N° de série</label>
        <input type="text" name="serial_number" value="${escapeHtml(tool?.serial_number || "")}"/>
      </div>
      <div class="field-row">
        <div class="field">
          <label>Date d'achat</label>
          <input type="date" name="purchase_date" value="${tool?.purchase_date ? tool.purchase_date.slice(0, 10) : ""}"/>
        </div>
        <div class="field">
          <label>Prix d'achat</label>
          <input type="number" step="0.01" min="0" name="purchase_price" value="${tool?.purchase_price ?? 0}"/>
        </div>
      </div>
      <div class="field">
        <label>Tarif journalier d'usage (€, vide = forfait par défaut)</label>
        <input type="number" step="0.01" min="0" name="daily_rate" value="${tool?.daily_rate ?? ""}"/>
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
      <div class="field">
        <label>État (0-5)</label>
        <input type="number" name="state" min="0" max="5" value="${tool?.state ?? 5}"/>
      </div>
      <div class="field">
        <label>Commentaire</label>
        <textarea name="comment" rows="2">${escapeHtml(tool?.comment || "")}</textarea>
      </div>
      ${editOnlyFields}
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

      root.querySelector("#ai-photo-input")?.addEventListener("change", async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        const statusEl = root.querySelector("#ai-photo-status");
        statusEl.textContent = "Analyse de la photo…";
        try {
          const res = await api.upload("/assistant/extract-from-photo", file);
          const f = res.fields || {};
          if (f.name) nameInput.value = f.name;
          if (f.type) typeInput.value = f.type;
          if (f.brand) form.querySelector('[name="brand"]').value = [f.brand, f.model].filter(Boolean).join(" ");
          if (f.serial_number) form.querySelector('[name="serial_number"]').value = f.serial_number;
          if (f.description) form.querySelector('[name="description"]').value = f.description;
          statusEl.textContent = `Champs suggérés (confiance ${f && res.confidence}) : à vérifier avant d'enregistrer.`;
        } catch (err) {
          statusEl.textContent = err instanceof ApiError ? err.message : "Analyse impossible";
        }
      });

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

      const stateInput = form.querySelector('[name="state"]');
      const statusSelect = form.querySelector('[name="status"]');
      const lossField = root.querySelector("#loss-reason-field");
      const assignedField = root.querySelector("#assigned-field");

      if (statusSelect) {
        function syncStatusFields() {
          lossField.style.display = statusSelect.value === "hors_service" ? "" : "none";
          assignedField.style.display = statusSelect.value === "dotation" ? "" : "none";
        }
        statusSelect.addEventListener("change", syncStatusFields);

        stateInput.addEventListener("input", () => {
          const value = Number(stateInput.value);
          if (value === 0) {
            statusSelect.value = "hors_service";
            form.querySelector('[name="loss_reason"]').value = "casse";
          } else if (value === 1) {
            statusSelect.value = "reparation";
          }
          syncStatusFields();
        });
      }

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(form).entries());
        const payload = {
          name: data.name,
          type: data.type || null,
          description: data.description || null,
          brand: data.brand || null,
          unique_code: data.unique_code,
          serial_number: data.serial_number || null,
          purchase_date: data.purchase_date ? new Date(data.purchase_date).toISOString() : null,
          purchase_price: data.purchase_price !== "" ? Number(data.purchase_price) : 0,
          daily_rate: data.daily_rate !== "" ? Number(data.daily_rate) : null,
          warranty_expiration_date: data.warranty_expiration_date ? new Date(data.warranty_expiration_date).toISOString() : null,
          state: Number(data.state),
          comment: data.comment || null,
        };
        if (isEdit) {
          payload.status = data.status;
          payload.loss_reason = data.loss_reason || null;
          payload.assigned_to_id = data.assigned_to_id ? Number(data.assigned_to_id) : null;
        }
        try {
          if (isEdit) {
            await api.patch(`/agency-tools/${tool.id}`, payload);
          } else {
            await api.post("/agency-tools", payload);
          }
          toast(isEdit ? "Outil mis à jour" : "Outil ajouté", "success");
          closeModal();
          onChanged();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}

function openPhotoForm(tool, onChanged) {
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
          await api.upload(`/agency-tools/${tool.id}/photo`, file);
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
