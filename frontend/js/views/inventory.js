import { api, ApiError } from "../api.js";
import {
  escapeHtml,
  formatDate,
  stateStars,
  agencyStatusBadge,
  toast,
  openModal,
  closeModal,
} from "../ui.js";
import { isManager } from "../state.js";
import { openToolHistory } from "../toolHistory.js";
import { openScanner } from "../scanner.js";
import { barcodeSVG, sanitizeForBarcode } from "../barcode.js";
import { icon } from "../icons.js";

const CONTROL_MAX_AGE_DAYS = 365;
const LOSS_REASONS = { vol: "Vol", casse: "Casse", perte: "Perte" };

const PAGE_SIZE = 100;
let currentTab = "todo";

function isOverdue(lastControlDate) {
  if (!lastControlDate) return true;
  const days = (Date.now() - new Date(lastControlDate).getTime()) / 86400000;
  return days > CONTROL_MAX_AGE_DAYS;
}

export async function renderInventory(app) {
  await draw(app);
}

async function draw(app) {
  const tools = await api.get("/agency-tools");

  const upToDate = tools.filter((t) => !isOverdue(t.last_control_date));
  const percent = tools.length ? Math.round((upToDate.length / tools.length) * 100) : 100;

  const filtered = currentTab === "todo" ? tools.filter((t) => isOverdue(t.last_control_date)) : tools;

  app.innerHTML = `
    <div class="section-header">
      <h1>Inventaire</h1>
      <div class="section-links">
        ${isManager() ? '<a href="#/etiquettes">Étiquettes</a>' : ""}
        <button class="btn btn-sm" id="scan-btn">${icon("camera", { size: 16 })} Scanner</button>
      </div>
    </div>

    <div class="card">
      <div class="card-sub">${upToDate.length} / ${tools.length} outils à jour (${percent}%)</div>
      <div style="height:8px;background:var(--surface-2);border-radius:4px;overflow:hidden;margin-top:0.4rem;">
        <div style="height:100%;width:${percent}%;background:var(--success);"></div>
      </div>
    </div>

    <div class="tag-row" id="inv-tabs">
      <button data-tab="todo" class="${currentTab === "todo" ? "active" : ""}">À contrôler</button>
      <button data-tab="all" class="${currentTab === "all" ? "active" : ""}">Tous les outils</button>
    </div>

    <div id="inv-list">
      ${filtered.length ? filtered.slice(0, PAGE_SIZE).map((t) => toolCard(t)).join("") : `<div class="empty-state">Rien à contrôler.</div>`}
    </div>
    ${filtered.length > PAGE_SIZE ? `<div class="load-more"><button class="btn" id="inv-more">Afficher plus (${PAGE_SIZE} sur ${filtered.length})</button></div>` : ""}
  `;

  document.querySelectorAll("#inv-tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentTab = btn.dataset.tab;
      draw(app);
    });
  });

  document.getElementById("scan-btn").addEventListener("click", () => {
    openScanner((value) => {
      const normalized = sanitizeForBarcode(value);
      const match = tools.find(
        (t) => sanitizeForBarcode(t.unique_code) === normalized || t.unique_code.toLowerCase() === value.toLowerCase()
      );
      if (match) {
        openControlForm(match, () => draw(app));
      } else {
        toast("Aucun outil trouvé pour ce code", "error");
      }
    });
  });

  let shown = Math.min(PAGE_SIZE, filtered.length);
  document.getElementById("inv-more")?.addEventListener("click", (e) => {
    document.getElementById("inv-list").insertAdjacentHTML("beforeend", filtered.slice(shown, shown + PAGE_SIZE).map((t) => toolCard(t)).join(""));
    shown = Math.min(shown + PAGE_SIZE, filtered.length);
    if (shown >= filtered.length) e.target.closest(".load-more").remove();
    else e.target.textContent = `Afficher plus (${shown} sur ${filtered.length})`;
    bindCards();
  });

  const bindCards = () => document.querySelectorAll("#inv-list [data-tool-id]:not([data-bound])").forEach((card) => {
    card.dataset.bound = "1";
    const id = Number(card.dataset.toolId);
    const tool = filtered.find((t) => t.id === id);
    card.querySelector('[data-action="control"]').addEventListener("click", () => openControlForm(tool, () => draw(app)));
    card.querySelector('[data-action="history"]').addEventListener("click", () => openToolHistory("agency", id, tool.name));
  });
  bindCards();
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
          <div class="card-sub">${escapeHtml(t.type || "-")} · ${escapeHtml(t.unique_code)}</div>
          <div class="card-meta">
            ${agencyStatusBadge(t.status)}
            <span>Contrôle : ${t.last_control_date ? formatDate(t.last_control_date) : "Jamais contrôlé"}</span>
            ${isOverdue(t.last_control_date) ? '<span class="badge badge-orange">Contrôle à faire</span>' : ""}
            ${!t.serial_number ? '<span class="badge badge-gray">N° série manquant</span>' : ""}
            ${!t.description ? '<span class="badge badge-gray">Description manquante</span>' : ""}
            ${t.status === "hors_service" && t.loss_reason ? `<span class="badge badge-red">${LOSS_REASONS[t.loss_reason] || t.loss_reason}</span>` : ""}
          </div>
        </div>
      </div>
      <div class="card-actions">
        <button class="btn btn-sm" data-action="control">Contrôler</button>
        <button class="btn btn-sm" data-action="history">Historique</button>
      </div>
    </div>
  `;
}

function openControlForm(tool, onDone) {
  const html = `
    <div class="modal-header">
      <div class="card-title">Contrôler — ${escapeHtml(tool.name)}</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <div style="text-align:center;margin-bottom:1rem;">${barcodeSVG(tool.unique_code, { moduleWidth: 1.6, height: 40 })}</div>
    <form id="control-form" class="form-grid">
      <div class="field">
        <label>État constaté (0-5)</label>
        <input type="number" name="state" min="0" max="5" value="${tool.state}" required/>
      </div>
      <div class="field">
        <label>Statut</label>
        <select name="status" id="ctrl-status">
          <option value="disponible" ${tool.status === "disponible" ? "selected" : ""}>Disponible</option>
          <option value="emprunte" ${tool.status === "emprunte" ? "selected" : ""}>Emprunté</option>
          <option value="reparation" ${tool.status === "reparation" ? "selected" : ""}>En réparation</option>
          <option value="hors_service" ${tool.status === "hors_service" ? "selected" : ""}>Hors service</option>
          <option value="dotation" ${tool.status === "dotation" ? "selected" : ""}>Dotation</option>
        </select>
      </div>
      <div class="field" id="ctrl-loss-field" style="${tool.status === "hors_service" ? "" : "display:none;"}">
        <label>Motif de perte</label>
        <select name="loss_reason">
          <option value="">-</option>
          ${Object.entries(LOSS_REASONS)
            .map(([k, v]) => `<option value="${k}" ${tool.loss_reason === k ? "selected" : ""}>${v}</option>`)
            .join("")}
        </select>
      </div>
      <div class="field">
        <label>Commentaire</label>
        <textarea name="comment" rows="2">${escapeHtml(tool.comment || "")}</textarea>
      </div>
      <div class="field">
        <label>N° de série ${!tool.serial_number ? "(manquant)" : ""}</label>
        <input type="text" name="serial_number" value="${escapeHtml(tool.serial_number || "")}"/>
      </div>
      <div class="field">
        <label>Description ${!tool.description ? "(manquante)" : ""}</label>
        <input type="text" name="description" value="${escapeHtml(tool.description || "")}"/>
      </div>
      <div class="field">
        <label>Photo (optionnel)</label>
        <input type="file" name="photo" accept="image/*" capture="environment"/>
      </div>
      <button type="submit" class="btn btn-primary">Enregistrer le contrôle</button>
    </form>
  `;

  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      const form = root.querySelector("#control-form");
      const stateInput = form.querySelector('[name="state"]');
      const statusSelect = root.querySelector("#ctrl-status");
      const lossField = root.querySelector("#ctrl-loss-field");

      statusSelect.addEventListener("change", () => {
        lossField.style.display = statusSelect.value === "hors_service" ? "" : "none";
      });

      stateInput.addEventListener("input", () => {
        const value = Number(stateInput.value);
        if (value === 0) {
          statusSelect.value = "hors_service";
          form.querySelector('[name="loss_reason"]').value = "casse";
          lossField.style.display = "";
        } else if (value === 1) {
          statusSelect.value = "reparation";
          lossField.style.display = "none";
        }
      });

      form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(form).entries());
        try {
          await api.post(`/agency-tools/${tool.id}/control`, {
            state: Number(data.state),
            status: data.status,
            loss_reason: data.status === "hors_service" ? data.loss_reason || null : null,
            comment: data.comment || null,
            serial_number: data.serial_number || null,
            description: data.description || null,
          });
          const file = form.querySelector('[name="photo"]').files[0];
          if (file) await api.upload(`/agency-tools/${tool.id}/photo`, file);
          toast("Contrôle enregistré", "success");
          closeModal();
          onDone();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}
