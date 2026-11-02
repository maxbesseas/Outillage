import { api, ApiError } from "../api.js";
import { escapeHtml, formatDate, toast, openModal, closeModal, confirmDialog } from "../ui.js";
import { isAdmin, isManager } from "../state.js";
import { getTeam } from "../usersCache.js";

const STATUS = { expired: ["red", "Expirée"], soon: ["orange", "Bientôt expirée"], ok: ["green", "Valide"] };

export async function renderQualifications(app) {
  const [qualifications, types, requirements] = await Promise.all([
    api.get("/qualifications"),
    api.get("/qualification-types"),
    api.get("/tool-requirements"),
  ]);
  const labels = Object.fromEntries(types.map((t) => [t.code, t.label]));

  app.innerHTML = `
    <div class="section-header">
      <h1>Habilitations</h1>
      <div class="section-links">
        <a href="#/controles">Contrôles</a>
        ${isManager() ? '<button class="btn btn-sm btn-primary" id="add-qual">Ajouter</button>' : ""}
      </div>
    </div>
    <p class="card-sub">Les habilitations exigées pour un outil sont vérifiées à la réservation (avertissement ou blocage selon les réglages).</p>
    ${
      qualifications.length
        ? qualifications
            .map((q) => {
              const [color, label] = STATUS[q.status];
              return `<div class="card" data-id="${q.id}">
        <div class="card-row"><div class="card-title">${escapeHtml(q.user_name || "-")} — ${escapeHtml(q.label)}</div>
          <span class="badge badge-${color}"><span class="dot"></span>${label}</span></div>
        <div class="card-meta"><span>Obtenue : ${q.obtained_at ? formatDate(q.obtained_at) : "-"}</span><span>Expire : ${q.expires_at ? formatDate(q.expires_at) : "sans limite"}</span>
          ${q.document_path ? `<a href="${escapeHtml(q.document_path)}" target="_blank" rel="noopener">Justificatif</a>` : ""}</div>
        ${isManager() ? '<div class="card-actions"><button class="btn btn-sm btn-danger" data-action="delete">Supprimer</button></div>' : ""}</div>`;
            })
            .join("")
        : `<div class="empty-state">Aucune habilitation enregistrée.</div>`
    }

    <h3>Exigences par outil</h3>
    ${
      requirements.length
        ? requirements
            .map(
              (r) => `<div class="card" data-req="${r.id}"><div class="card-row">
          <span>${r.tool_type ? `Type « ${escapeHtml(r.tool_type)} »` : `Outil n°${r.agency_tool_id}`} → <strong>${escapeHtml(labels[r.qualification_code] || r.qualification_code)}</strong>
          ${r.blocking ? '<span class="badge badge-red">bloquant</span>' : '<span class="badge badge-gray">avertissement</span>'}</span>
          ${isManager() ? '<button class="btn btn-sm btn-danger" data-action="del-req">Retirer</button>' : ""}</div></div>`
            )
            .join("")
        : `<div class="empty-state">Aucune exigence définie.</div>`
    }
    ${isAdmin() ? `<h3>Types d'habilitation</h3>
      <div>${types.map((t) => `<span class="badge badge-blue">${escapeHtml(t.label)} (${escapeHtml(t.code)})</span> `).join("")}</div>
      <form id="type-form" class="filter-bar"><input name="code" placeholder="Code" required/><input name="label" placeholder="Libellé" required/><button class="btn btn-sm btn-primary">Ajouter un type</button></form>
      <form id="req-form" class="filter-bar"><input name="tool_type" placeholder="Type d'outil exact" required/>
        <select name="code">${types.map((t) => `<option value="${escapeHtml(t.code)}">${escapeHtml(t.label)}</option>`).join("")}</select>
        <label><input type="checkbox" name="blocking"/> bloquant</label><button class="btn btn-sm btn-primary">Exiger</button></form>` : ""}
  `;

  const refresh = () => renderQualifications(app);

  app.querySelectorAll('[data-action="delete"]').forEach((btn) =>
    btn.addEventListener("click", async () => {
      if (!(await confirmDialog("Supprimer cette habilitation ?", { danger: true }))) return;
      await api.delete(`/qualifications/${btn.closest(".card").dataset.id}`);
      refresh();
    })
  );
  app.querySelectorAll('[data-action="del-req"]').forEach((btn) =>
    btn.addEventListener("click", async () => {
      try {
        await api.delete(`/tool-requirements/${btn.closest(".card").dataset.req}`);
        refresh();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Erreur", "error");
      }
    })
  );

  const typeForm = document.getElementById("type-form");
  if (typeForm)
    typeForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(typeForm);
      try {
        await api.post("/qualification-types", { code: f.get("code"), label: f.get("label") });
        refresh();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Erreur", "error");
      }
    });
  const reqForm = document.getElementById("req-form");
  if (reqForm)
    reqForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = new FormData(reqForm);
      try {
        await api.post("/tool-requirements", { tool_type: f.get("tool_type"), qualification_code: f.get("code"), blocking: f.has("blocking") });
        refresh();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Erreur", "error");
      }
    });

  const add = document.getElementById("add-qual");
  if (add)
    add.addEventListener("click", async () => {
      const team = await getTeam();
      openModal(
        `<div class="modal-header"><div class="card-title">Nouvelle habilitation</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
        <form id="q-form" class="form-grid">
          <div class="field"><label>Salarié</label><select name="user_id">${team.map((u) => `<option value="${u.id}">${escapeHtml(u.full_name)}</option>`).join("")}</select></div>
          <div class="field"><label>Habilitation</label><select name="code">${types.map((t) => `<option value="${escapeHtml(t.code)}">${escapeHtml(t.label)}</option>`).join("")}</select></div>
          <div class="field-row"><div class="field"><label>Obtenue le</label><input type="date" name="obtained_at"/></div>
            <div class="field"><label>Expire le</label><input type="date" name="expires_at"/></div></div>
          <div class="field"><label>Justificatif (PDF ou image)</label><input type="file" name="document" accept="application/pdf,image/*"/></div>
          <button type="submit" class="btn btn-primary">Enregistrer</button>
        </form>`,
        {
          onMount: (root) => {
            root.querySelector("#c").addEventListener("click", closeModal);
            root.querySelector("#q-form").addEventListener("submit", async (e) => {
              e.preventDefault();
              const f = new FormData(e.target);
              const iso = (v) => (v ? new Date(v).toISOString() : null);
              try {
                const created = await api.post("/qualifications", {
                  user_id: Number(f.get("user_id")),
                  code: f.get("code"),
                  obtained_at: iso(f.get("obtained_at")),
                  expires_at: iso(f.get("expires_at")),
                });
                const file = f.get("document");
                if (file && file.size) await api.upload(`/qualifications/${created.id}/document`, file);
                closeModal();
                refresh();
              } catch (err) {
                toast(err instanceof ApiError ? err.message : "Erreur", "error");
              }
            });
          },
        }
      );
    });
}
