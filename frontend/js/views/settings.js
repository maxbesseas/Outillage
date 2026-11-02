import { api, ApiError } from "../api.js";
import { escapeHtml, toast, openModal, closeModal, confirmDialog } from "../ui.js";
import { invalidateAgencies } from "../agencies.js";
import { renderAppSettingsSection } from "./appSettings.js";

export async function renderSettings(app) {
  const [settings, agencies] = await Promise.all([api.get("/settings"), api.get("/agencies?include_inactive=true")]);

  app.innerHTML = `
    <div class="section-header">
      <h1>Paramètres</h1>
      <div class="section-links"><a href="#/audit">Journal d'audit</a><a href="#/taches">Tâches planifiées</a><a href="#/sauvegardes">Sauvegardes</a><a href="#/import">Import</a><a href="#/assistant-suivi">Assistant</a><a href="#/exports">Exports</a></div>
    </div>

    <div class="section-header"><h3>Agences</h3><button class="btn btn-sm btn-primary" id="add-agency">Ajouter une agence</button></div>
    <div id="agency-list">
      ${
        agencies.length
          ? agencies
              .map(
                (a) => `
        <div class="card" data-agency-id="${a.id}">
          <div class="card-row">
            <div class="card-title">${escapeHtml(a.name)}</div>
            <span class="badge ${a.is_active ? "badge-green" : "badge-gray"}"><span class="dot"></span>${a.is_active ? "Active" : "Inactive"}</span>
          </div>
          <div class="card-meta">
            <span>Code : ${escapeHtml(a.code || "-")}</span>
            <span>Registre Excel : ${escapeHtml(a.excel_registry_name || a.name)}</span>
          </div>
          <div class="card-actions">
            <button class="btn btn-sm" data-action="edit">Modifier</button>
            <button class="btn btn-sm" data-action="toggle">${a.is_active ? "Désactiver" : "Réactiver"}</button>
            <button class="btn btn-sm btn-danger" data-action="delete">Supprimer</button>
          </div>
        </div>`
              )
              .join("")
          : `<div class="empty-state">Aucune agence.</div>`
      }
    </div>

    <div id="app-settings-section"></div>

    <h3>Notifications email et serveur d'envoi</h3>
    <form id="settings-form" class="form-grid">
      <div class="field">
        <label>Email magasinier</label>
        <input type="email" name="magasinier_email" value="${escapeHtml(settings.magasinier_email || "")}"/>
      </div>

      <h3>Serveur d'envoi (SMTP)</h3>

      <div class="field-row">
        <div class="field">
          <label>Hôte</label>
          <input type="text" name="smtp_host" value="${escapeHtml(settings.smtp_host || "")}"/>
        </div>
        <div class="field">
          <label>Port</label>
          <input type="number" name="smtp_port" value="${settings.smtp_port ?? 587}"/>
        </div>
      </div>
      <div class="field">
        <label>Utilisateur</label>
        <input type="text" name="smtp_username" value="${escapeHtml(settings.smtp_username || "")}"/>
      </div>
      <div class="field">
        <label>Mot de passe</label>
        <input type="password" name="smtp_password" autocomplete="new-password" placeholder="${settings.smtp_password_set ? "déjà enregistré — laisser vide pour ne pas changer" : ""}"/>
      </div>
      <div class="field">
        <label>Email expéditeur (optionnel)</label>
        <input type="email" name="smtp_from_email" value="${escapeHtml(settings.smtp_from_email || "")}"/>
      </div>
      <div class="field">
        <label>TLS</label>
        <select name="smtp_use_tls">
          <option value="true" ${settings.smtp_use_tls ? "selected" : ""}>Oui</option>
          <option value="false" ${!settings.smtp_use_tls ? "selected" : ""}>Non</option>
        </select>
      </div>
      <button type="submit" class="btn btn-primary">Enregistrer</button>
    </form>
  `;

  const refresh = () => {
    invalidateAgencies();
    renderSettings(document.getElementById("app"));
  };

  renderAppSettingsSection(document.getElementById("app-settings-section"));

  document.getElementById("add-agency").addEventListener("click", () => openAgencyForm(null, refresh));

  app.querySelectorAll("[data-agency-id]").forEach((card) => {
    const agency = agencies.find((a) => a.id === Number(card.dataset.agencyId));
    card.querySelector('[data-action="edit"]').addEventListener("click", () => openAgencyForm(agency, refresh));
    card.querySelector('[data-action="toggle"]').addEventListener("click", async () => {
      try {
        await api.patch(`/agencies/${agency.id}`, { is_active: !agency.is_active });
        refresh();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Erreur", "error");
      }
    });
    card.querySelector('[data-action="delete"]').addEventListener("click", async () => {
      if (!(await confirmDialog(`Supprimer l'agence « ${agency.name} » ?`, { danger: true }))) return;
      try {
        await api.delete(`/agencies/${agency.id}`);
        toast("Agence supprimée", "success");
        refresh();
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Erreur", "error");
      }
    });
  });

  document.getElementById("settings-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(e.target).entries());
    const payload = {
      magasinier_email: data.magasinier_email || null,
      smtp_host: data.smtp_host || null,
      smtp_port: data.smtp_port ? Number(data.smtp_port) : null,
      smtp_username: data.smtp_username || null,
      smtp_from_email: data.smtp_from_email || null,
      smtp_use_tls: data.smtp_use_tls === "true",
    };
    if (data.smtp_password) payload.smtp_password = data.smtp_password;

    try {
      await api.patch("/settings", payload);
      toast("Paramètres enregistrés", "success");
      renderSettings(document.getElementById("app"));
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur", "error");
    }
  });
}

function openAgencyForm(agency, onDone) {
  const isEdit = !!agency;
  openModal(
    `
    <div class="modal-header">
      <div class="card-title">${isEdit ? "Modifier l'agence" : "Nouvelle agence"}</div>
      <button class="btn btn-ghost btn-sm" id="agency-close">Fermer</button>
    </div>
    <form id="agency-form" class="form-grid">
      <div class="field">
        <label>Nom (référence utilisée par les comptes et le matériel)</label>
        <input type="text" name="name" value="${escapeHtml(agency?.name || "")}" required maxlength="80"/>
      </div>
      <div class="field">
        <label>Code (optionnel)</label>
        <input type="text" name="code" value="${escapeHtml(agency?.code || "")}" maxlength="30"/>
      </div>
      <div class="field">
        <label>Nom du registre Excel (optionnel, sinon le nom de l'agence)</label>
        <input type="text" name="excel_registry_name" value="${escapeHtml(agency?.excel_registry_name || "")}" maxlength="120"/>
      </div>
      ${isEdit ? '<p class="card-sub">Renommer l\'agence met à jour tous les comptes et le matériel qui lui sont rattachés.</p>' : ""}
      <button type="submit" class="btn btn-primary">${isEdit ? "Enregistrer" : "Créer"}</button>
    </form>
  `,
    {
      onMount: (root) => {
        root.querySelector("#agency-close").addEventListener("click", closeModal);
        root.querySelector("#agency-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const data = Object.fromEntries(new FormData(e.target).entries());
          const payload = {
            name: data.name.trim(),
            code: data.code || null,
            excel_registry_name: data.excel_registry_name || null,
          };
          try {
            if (isEdit) await api.patch(`/agencies/${agency.id}`, payload);
            else await api.post("/agencies", payload);
            toast(isEdit ? "Agence mise à jour" : "Agence créée", "success");
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
