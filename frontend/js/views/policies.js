import { api, ApiError } from "../api.js";
import { escapeHtml, toast, openModal, closeModal, confirmDialog } from "../ui.js";

const KIND_LABEL = { agency: "Outil d'agence", epi: "EPI", personal: "Outil personnel" };

export async function renderPolicies(app) {
  const [policies, templates] = await Promise.all([api.get("/inspection-policies"), api.get("/inspection-templates")]);

  app.innerHTML = `
    <div class="section-header">
      <h1>Périodicités de contrôle</h1>
      <div class="section-links"><a href="#/controles">Contrôles</a><button class="btn btn-sm btn-primary" id="add-policy">Ajouter</button></div>
    </div>
    <p class="card-sub">Aucune valeur réglementaire n'est imposée par l'application : les périodicités ci-dessous sont à valider par le responsable sécurité. Sans règle pour un type, la périodicité par défaut des réglages avancés s'applique.</p>
    <div class="table-scroll"><table class="simple-table">
      <thead><tr><th>Genre</th><th>Type</th><th>Périodicité</th><th>Alerte</th><th>Exigences</th><th></th></tr></thead>
      <tbody>
      ${
        policies.length
          ? policies
              .map(
                (p) => `<tr data-id="${p.id}">
          <td>${KIND_LABEL[p.tool_kind] || p.tool_kind}</td><td>${escapeHtml(p.type || "Tous les types")}</td>
          <td>${p.periodicity_days} j</td><td>${p.warn_before_days} j avant</td>
          <td>${[p.requires_photo && "photo", p.requires_report && "rapport", p.requires_calibration && "étalonnage"].filter(Boolean).join(", ") || "-"}</td>
          <td><button class="btn btn-sm" data-action="edit">Modifier</button> <button class="btn btn-sm btn-danger" data-action="delete">Supprimer</button></td></tr>`
              )
              .join("")
          : `<tr><td colspan="6">Aucune règle spécifique.</td></tr>`
      }
      </tbody></table></div>

    <div class="section-header"><h3>Points de contrôle par type</h3><button class="btn btn-sm btn-primary" id="add-template">Ajouter un modèle</button></div>
    <div id="template-list">
      ${
        templates.length
          ? templates
              .map(
                (t) => `<div class="card" data-template="${t.id}">
          <div class="card-row"><div class="card-title">${KIND_LABEL[t.tool_kind]} — ${escapeHtml(t.type)}</div>
            <button class="btn btn-sm" data-action="edit-template">Modifier</button></div>
          <div class="card-sub">${t.items.map((i) => escapeHtml(i.label) + (i.required ? " *" : "")).join(" · ") || "Aucun point"}</div></div>`
              )
              .join("")
          : `<div class="empty-state">Aucun modèle de checklist.</div>`
      }
    </div>
  `;

  const refresh = () => renderPolicies(app);
  document.getElementById("add-policy").addEventListener("click", () => policyForm(null, refresh));
  document.getElementById("add-template").addEventListener("click", () => templateForm(null, refresh));
  app.querySelectorAll("tr[data-id]").forEach((row) => {
    const policy = policies.find((p) => p.id === Number(row.dataset.id));
    row.querySelector('[data-action="edit"]').addEventListener("click", () => policyForm(policy, refresh));
    row.querySelector('[data-action="delete"]').addEventListener("click", async () => {
      if (!(await confirmDialog("Supprimer cette règle ?", { danger: true }))) return;
      await api.delete(`/inspection-policies/${policy.id}`);
      refresh();
    });
  });
  app.querySelectorAll("[data-template]").forEach((card) => {
    const template = templates.find((t) => t.id === Number(card.dataset.template));
    card.querySelector('[data-action="edit-template"]').addEventListener("click", () => templateForm(template, refresh));
  });
}

function policyForm(policy, onDone) {
  const isEdit = !!policy;
  openModal(
    `<div class="modal-header"><div class="card-title">${isEdit ? "Modifier la règle" : "Nouvelle règle"}</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    <form id="policy-form" class="form-grid">
      <div class="field"><label>Genre</label><select name="tool_kind" ${isEdit ? "disabled" : ""}>
        ${Object.entries(KIND_LABEL).map(([k, v]) => `<option value="${k}" ${policy?.tool_kind === k ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      <div class="field"><label>Type (vide = tous les types du genre)</label><input name="type" value="${escapeHtml(policy?.type || "")}" ${isEdit ? "readonly" : ""} placeholder="ex. Moyens d'accès en hauteur"/></div>
      <div class="field-row">
        <div class="field"><label>Périodicité (jours)</label><input type="number" name="periodicity_days" min="1" value="${policy?.periodicity_days ?? 365}" required/></div>
        <div class="field"><label>Prévenir (jours avant)</label><input type="number" name="warn_before_days" min="0" value="${policy?.warn_before_days ?? 30}" required/></div>
      </div>
      <label><input type="checkbox" name="requires_photo" ${policy?.requires_photo ? "checked" : ""}/> Photo obligatoire</label>
      <label><input type="checkbox" name="requires_report" ${policy?.requires_report ? "checked" : ""}/> Rapport de vérification attendu</label>
      <label><input type="checkbox" name="requires_calibration" ${policy?.requires_calibration ? "checked" : ""}/> Instrument à étalonner</label>
      <div class="field"><label>Périodicité d'étalonnage (jours)</label><input type="number" name="calibration_periodicity_days" min="1" value="${policy?.calibration_periodicity_days ?? ""}"/></div>
      <button type="submit" class="btn btn-primary">Enregistrer</button>
    </form>`,
    {
      onMount: (root) => {
        root.querySelector("#c").addEventListener("click", closeModal);
        root.querySelector("#policy-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          const body = {
            periodicity_days: Number(f.get("periodicity_days")),
            warn_before_days: Number(f.get("warn_before_days")),
            requires_photo: f.has("requires_photo"),
            requires_report: f.has("requires_report"),
            requires_calibration: f.has("requires_calibration"),
            calibration_periodicity_days: f.get("calibration_periodicity_days") ? Number(f.get("calibration_periodicity_days")) : null,
          };
          try {
            if (isEdit) await api.patch(`/inspection-policies/${policy.id}`, body);
            else await api.post("/inspection-policies", { ...body, tool_kind: f.get("tool_kind"), type: f.get("type") || null });
            closeModal();
            onDone();
          } catch (err) {
            toast(err instanceof ApiError ? err.message : "Erreur", "error");
          }
        });
      },
    }
  );
}

function templateForm(template, onDone) {
  const items = template ? template.items.map((i) => ({ ...i })) : [{ id: "point1", label: "", required: true }];
  openModal(
    `<div class="modal-header"><div class="card-title">Points de contrôle</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    <form id="tpl-form" class="form-grid">
      <div class="field"><label>Genre</label><select name="tool_kind" ${template ? "disabled" : ""}>
        ${Object.entries(KIND_LABEL).map(([k, v]) => `<option value="${k}" ${template?.tool_kind === k ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      <div class="field"><label>Type exact du matériel</label><input name="type" value="${escapeHtml(template?.type || "")}" ${template ? "readonly" : "required"}/></div>
      <div id="tpl-items"></div>
      <button type="button" class="btn btn-sm" id="tpl-add">Ajouter un point</button>
      <button type="submit" class="btn btn-primary">Enregistrer</button>
    </form>`,
    {
      onMount: (root) => {
        const list = root.querySelector("#tpl-items");
        function paint() {
          list.innerHTML = items
            .map(
              (it, idx) => `<div class="field-row tpl-row" data-idx="${idx}">
              <input value="${escapeHtml(it.label)}" placeholder="Libellé du point" data-field="label" aria-label="Libellé"/>
              <label><input type="checkbox" data-field="required" ${it.required ? "checked" : ""}/> obligatoire</label>
              <button type="button" class="btn btn-sm btn-danger" data-remove="${idx}">Retirer</button></div>`
            )
            .join("");
          list.querySelectorAll(".tpl-row").forEach((row) => {
            const idx = Number(row.dataset.idx);
            row.querySelector('[data-field="label"]').addEventListener("input", (e) => (items[idx].label = e.target.value));
            row.querySelector('[data-field="required"]').addEventListener("change", (e) => (items[idx].required = e.target.checked));
            row.querySelector("[data-remove]").addEventListener("click", () => {
              items.splice(idx, 1);
              paint();
            });
          });
        }
        paint();
        root.querySelector("#c").addEventListener("click", closeModal);
        root.querySelector("#tpl-add").addEventListener("click", () => {
          items.push({ id: `point${Date.now().toString(36)}`, label: "", required: false });
          paint();
        });
        root.querySelector("#tpl-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          const clean = items.filter((i) => i.label.trim()).map((i, n) => ({ id: i.id || `point${n}`, label: i.label.trim(), required: !!i.required }));
          try {
            await api.put("/inspection-templates", { tool_kind: template ? template.tool_kind : f.get("tool_kind"), type: template ? template.type : f.get("type"), items: clean });
            closeModal();
            onDone();
          } catch (err) {
            toast(err instanceof ApiError ? err.message : "Erreur", "error");
          }
        });
      },
    }
  );
}
