import { api, ApiError } from "../api.js";
import { escapeHtml, formatDate, toast, openModal, closeModal, confirmDialog } from "../ui.js";
import { state } from "../state.js";
import { getAllUsers, getUserName } from "../usersCache.js";
import { openToolHistory } from "../toolHistory.js";
import { openScanner } from "../scanner.js";
import { icon } from "../icons.js";

const STATUS_MAP = {
  en_attente: ["orange", "En attente"],
  confirme: ["blue", "En cours"],
  refuse: ["red", "Refusé"],
  termine: ["green", "Terminé"],
};

let currentTab = "active";

function nameOrYou(id) {
  return id === state.user.id ? "Vous" : getUserName(id);
}

export async function renderPeerTransfers(app) {
  await draw(app);
}

async function draw(app) {
  const [transfers] = await Promise.all([api.get("/peer-transfers"), getAllUsers()]);

  app.innerHTML = `
    <div class="section-header"><h1>Transferts entre collègues</h1></div>
    <div class="card">
      Déclarez qu'un outil personnel change de détenteur entre deux salariés. La partie qui n'a pas déclaré le transfert doit le confirmer.
    </div>
    <div class="tag-row" id="pt-tabs">
      <button data-tab="active" class="${currentTab === "active" ? "active" : ""}">En cours</button>
      <button data-tab="done" class="${currentTab === "done" ? "active" : ""}">Rendus</button>
    </div>
    <div id="pt-body"></div>
    <button class="fab" id="add-pt-fab" aria-label="Nouveau prêt entre collègues">${icon("plus", { size: 22 })}</button>
  `;

  document.querySelectorAll("#pt-tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      currentTab = btn.dataset.tab;
      draw(app);
    });
  });

  document.getElementById("add-pt-fab").addEventListener("click", () => openDeclareForm(() => draw(app)));

  const body = document.getElementById("pt-body");

  if (currentTab === "active") {
    const toConfirm = transfers.filter((t) => t.status === "en_attente" && t.declared_by_id !== state.user.id);
    const waiting = transfers.filter((t) => t.status === "en_attente" && t.declared_by_id === state.user.id);
    const ongoing = transfers.filter((t) => t.status === "confirme");

    body.innerHTML = `
      ${section("À confirmer", toConfirm, "confirm")}
      ${section("En attente de l'autre partie", waiting, "none")}
      ${section("En cours", ongoing, "return")}
      ${!toConfirm.length && !waiting.length && !ongoing.length ? `<div class="empty-state">Rien en cours.</div>` : ""}
    `;
  } else {
    const done = transfers.filter((t) => t.status === "termine" || t.status === "refuse");
    body.innerHTML = done.length ? done.map((t) => card(t, "none")).join("") : `<div class="empty-state">Aucun transfert.</div>`;
  }

  wireActions(body, () => draw(app));
}

function section(title, items, mode) {
  if (!items.length) return "";
  return `<h3>${title}</h3>${items.map((t) => card(t, mode)).join("")}`;
}

function card(t, mode) {
  const [color, label] = STATUS_MAP[t.status] || ["gray", t.status];
  return `
    <div class="card" data-pt-id="${t.id}">
      <div class="card-row">
        <div class="card-title">${nameOrYou(t.from_user_id)} → ${nameOrYou(t.to_user_id)}</div>
        <span class="badge badge-${color}"><span class="dot"></span>${label}</span>
      </div>
      <div class="card-meta">
        <span>Déclaré le : ${formatDate(t.transfer_date)}</span>
        ${t.planned_return_date ? `<span>Retour prévu : ${formatDate(t.planned_return_date)}</span>` : ""}
        ${t.actual_return_date ? `<span>Rendu le : ${formatDate(t.actual_return_date)}</span>` : ""}
      </div>
      ${t.comment ? `<div class="card-sub">${escapeHtml(t.comment)}</div>` : ""}
      ${t.status === "termine" ? `<div class="card-sub">État : ${t.state_before ?? "-"}/5 → ${t.state_after ?? "-"}/5</div>` : ""}
      <div class="card-actions">
        ${mode === "confirm" ? '<button class="btn btn-sm" data-action="confirm">Confirmer</button><button class="btn btn-sm btn-danger" data-action="reject">Refuser</button>' : ""}
        ${mode === "return" ? '<button class="btn btn-sm" data-action="return">Marquer rendu</button>' : ""}
        <button class="btn btn-sm" data-action="history">Historique</button>
      </div>
    </div>
  `;
}

function wireActions(container, onDone) {
  container.querySelectorAll("[data-pt-id]").forEach((el) => {
    const id = Number(el.dataset.ptId);

    const confirmBtn = el.querySelector('[data-action="confirm"]');
    if (confirmBtn) {
      confirmBtn.addEventListener("click", async () => {
        try {
          await api.post(`/peer-transfers/${id}/confirm`);
          toast("Transfert confirmé", "success");
          onDone();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    }

    const rejectBtn = el.querySelector('[data-action="reject"]');
    if (rejectBtn) {
      rejectBtn.addEventListener("click", async () => {
        if (!(await confirmDialog("Refuser ce transfert ?", { danger: true }))) return;
        try {
          await api.post(`/peer-transfers/${id}/reject`);
          toast("Transfert refusé", "success");
          onDone();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    }

    const returnBtn = el.querySelector('[data-action="return"]');
    if (returnBtn) {
      returnBtn.addEventListener("click", () => {
        openReturnForm(id, onDone);
      });
    }

    el.querySelector('[data-action="history"]').addEventListener("click", async () => {
      const transfer = await api.get(`/peer-transfers`).then((list) => list.find((t) => t.id === id));
      openToolHistory("personal", transfer.tool_id, "Transfert entre collègues");
    });
  });
}

async function openDeclareForm(onDone) {
  const users = await getAllUsers();
  const others = users.filter((u) => u.id !== state.user.id);

  const html = `
    <div class="modal-header">
      <div class="card-title">Déclarer un transfert</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <form id="pt-form" class="form-grid">
      <div class="field">
        <label>Sens</label>
        <select name="direction">
          <option value="je_donne">Je donne l'outil</option>
          <option value="je_recois">Je reçois l'outil</option>
        </select>
      </div>
      <div class="field">
        <label>Code de l'outil</label>
        <div style="display:flex;gap:0.4rem;">
          <input type="text" name="tool_code" id="pt-tool-code" required style="flex:1;"/>
          <button type="button" class="btn btn-sm" id="pt-scan-btn">${icon("camera", { size: 16 })}</button>
        </div>
        <div class="card-sub" id="pt-tool-preview"></div>
      </div>
      <div class="field">
        <label>Collègue concerné</label>
        <select name="counterpart_id" required>
          <option value="">-</option>
          ${others.map((u) => `<option value="${u.id}">${escapeHtml(u.full_name)}</option>`).join("")}
        </select>
      </div>
      <div class="field">
        <label>Date de retour prévue</label>
        <input type="date" name="planned_return_date"/>
      </div>
      <div class="field">
        <label>Commentaire</label>
        <textarea name="comment" rows="2"></textarea>
      </div>
      <button type="submit" class="btn btn-primary">Déclarer</button>
    </form>
  `;

  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      const codeInput = root.querySelector("#pt-tool-code");
      const preview = root.querySelector("#pt-tool-preview");

      async function lookup() {
        const code = codeInput.value.trim();
        if (!code) {
          preview.textContent = "";
          return;
        }
        try {
          const tool = await api.get(`/personal-tools/lookup/${encodeURIComponent(code)}`);
          preview.textContent = `Trouvé : ${tool.name} (propriétaire : ${tool.owner_name})`;
        } catch {
          preview.textContent = "Aucun outil trouvé";
        }
      }
      codeInput.addEventListener("blur", lookup);

      root.querySelector("#pt-scan-btn").addEventListener("click", () => {
        openScanner((value) => {
          codeInput.value = value;
          lookup();
        });
      });

      root.querySelector("#pt-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        try {
          await api.post("/peer-transfers", {
            direction: data.direction,
            tool_code: data.tool_code,
            counterpart_id: Number(data.counterpart_id),
            planned_return_date: data.planned_return_date ? new Date(data.planned_return_date).toISOString() : null,
            comment: data.comment || null,
          });
          toast("Transfert déclaré", "success");
          closeModal();
          onDone();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}

function openReturnForm(transferId, onDone) {
  const html = `
    <div class="modal-header">
      <div class="card-title">Marquer rendu</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <form id="pt-return-form" class="form-grid">
      <div class="field">
        <label>État constaté au retour (0-5)</label>
        <input type="number" name="state_after" min="0" max="5" value="5" required/>
      </div>
      <div class="field">
        <label>Commentaire</label>
        <textarea name="comment" rows="2"></textarea>
      </div>
      <button type="submit" class="btn btn-primary">Confirmer</button>
    </form>
  `;
  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      root.querySelector("#pt-return-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        try {
          await api.post(`/peer-transfers/${transferId}/return`, {
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
