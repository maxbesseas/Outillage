import { api, ApiError } from "../api.js";
import { escapeHtml, formatDate, toast, openModal, closeModal, confirmDialog } from "../ui.js";
import { state, isAdmin } from "../state.js";
import { ROLE_LABELS, CHILD_ROLE, PARENT_ROLE } from "../roles.js";
import { invalidateUsers } from "../usersCache.js";
import { getAgencies } from "../agencies.js";
import { openDepartureWizard } from "../departureWizard.js";
import { icon } from "../icons.js";

export async function renderUsers(app) {
  await draw(app);
}

async function draw(app) {
  const [team, allUsers] = await Promise.all([api.get("/users/team"), api.get("/users")]);

  app.innerHTML = `
    <div class="section-header"><h1>${isAdmin() ? "Utilisateurs" : "Mon équipe"}</h1></div>
    <div id="users-list">
      ${team.length ? team.map((u) => userCard(u)).join("") : `<div class="empty-state">Aucun utilisateur.</div>`}
    </div>
    <button class="fab" id="add-user-fab" aria-label="Ajouter un utilisateur">${icon("plus", { size: 22 })}</button>
  `;

  document.getElementById("add-user-fab").addEventListener("click", () => openUserForm(null, allUsers, () => draw(app)));

  document.querySelectorAll("#users-list [data-user-id]").forEach((card) => {
    const id = Number(card.dataset.userId);
    const editBtn = card.querySelector('[data-action="edit"]');
    if (editBtn) {
      editBtn.addEventListener("click", async () => {
        const user = await api.get(`/users/${id}`);
        openUserForm(user, allUsers, () => draw(app));
      });
    }
    const resetBtn = card.querySelector('[data-action="reset"]');
    if (resetBtn) {
      resetBtn.addEventListener("click", async () => {
        if (!(await confirmDialog("Générer un mot de passe temporaire pour cet utilisateur ? Ses sessions seront fermées.", { danger: true }))) return;
        try {
          const res = await api.post(`/users/${id}/reset-password`);
          openModal(`
            <div class="modal-header"><div class="card-title">Mot de passe temporaire</div>
              <button class="btn btn-ghost btn-sm" id="temp-close">Fermer</button></div>
            <p class="card-sub">Communiquez ce mot de passe à l'utilisateur. Il devra le changer dès sa prochaine connexion. Il ne sera plus affiché.</p>
            <div class="card"><div class="card-title temp-password">${escapeHtml(res.temporary_password)}</div></div>
          `, { onMount: (root) => root.querySelector("#temp-close").addEventListener("click", closeModal) });
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    }
    const reassignBtn = card.querySelector('[data-action="reassign"]');
    if (reassignBtn) {
      reassignBtn.addEventListener("click", () => {
        const source = team.find((u) => u.id === id);
        const candidates = team.filter((u) => u.id !== id && u.is_active && (isAdmin() || u.agency_number === source.agency_number));
        if (!candidates.length) {
          toast("Aucun collègue disponible pour recevoir le matériel", "error");
          return;
        }
        openModal(`
          <div class="modal-header"><div class="card-title">Réaffecter le matériel de ${escapeHtml(source.full_name)}</div>
            <button class="btn btn-ghost btn-sm" id="reassign-close">Fermer</button></div>
          <form id="reassign-form" class="form-grid">
            <p class="card-sub">Ses outils personnels détenus, EPI assignés et dotations passent au collègue choisi. Les réservations en cours ne sont pas modifiées.</p>
            <div class="field"><label>Nouveau détenteur</label>
              <select name="to">${candidates.map((u) => `<option value="${u.id}">${escapeHtml(u.full_name)}</option>`).join("")}</select></div>
            <button type="submit" class="btn btn-primary">Réaffecter</button>
          </form>
        `, {
          onMount: (root) => {
            root.querySelector("#reassign-close").addEventListener("click", closeModal);
            root.querySelector("#reassign-form").addEventListener("submit", async (e) => {
              e.preventDefault();
              const to = Number(new FormData(e.target).get("to"));
              try {
                const res = await api.post(`/users/${id}/reassign-tools`, { to_user_id: to });
                toast(`${res.personal_tools} outil(s), ${res.epi} EPI et ${res.dotations} dotation(s) réaffecté(s)`, "success");
                closeModal();
              } catch (err) {
                toast(err instanceof ApiError ? err.message : "Erreur", "error");
              }
            });
          },
        });
      });
    }
    card.querySelector('[data-action="depart"]')?.addEventListener("click", () => {
      const user = team.find((u) => u.id === id);
      openDepartureWizard(user, team, () => {
        invalidateUsers();
        draw(app);
      });
    });
    card.querySelector('[data-action="anonymize"]')?.addEventListener("click", async () => {
      if (!(await confirmDialog("Anonymiser ce compte ? Nom, identifiant, email et téléphone seront effacés définitivement ; l'historique métier est conservé.", { danger: true }))) return;
      try {
        await api.post(`/gdpr/anonymize/${id}`);
        invalidateUsers();
        toast("Compte anonymisé", "success");
        draw(app);
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Erreur", "error");
      }
    });
    const deleteBtn = card.querySelector('[data-action="delete"]');
    const mfaResetBtn = card.querySelector('[data-action="mfa-reset"]');
    if (mfaResetBtn) {
      mfaResetBtn.addEventListener("click", async () => {
        if (!(await confirmDialog("Réinitialiser la double authentification de ce compte ?", { danger: true }))) return;
        try {
          await api.post(`/users/${id}/mfa-reset`);
          toast("Double authentification réinitialisée", "success");
          draw(app);
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    }

    if (deleteBtn) {
      deleteBtn.addEventListener("click", async () => {
        if (!(await confirmDialog("Supprimer cet utilisateur ?", { danger: true }))) return;
        try {
          await api.delete(`/users/${id}`);
          invalidateUsers();
          toast("Utilisateur supprimé", "success");
          draw(app);
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    }
  });
}

function userCard(u) {
  return `
    <div class="card" data-user-id="${u.id}">
      <div class="card-row">
        <div class="card-title">${escapeHtml(u.full_name)}</div>
        <span class="badge ${u.is_active ? "badge-green" : "badge-gray"}"><span class="dot"></span>${u.is_active ? "Actif" : "Inactif"}</span>
      </div>
      <div class="card-sub">@${escapeHtml(u.username)}</div>
      <div class="card-meta">
        <span>${ROLE_LABELS[u.role] || u.role}</span>
        <span>Agence : ${escapeHtml(u.agency_number || "-")}</span>
        <span>Créé le : ${formatDate(u.created_at)}</span>
      </div>
      <div class="card-actions">
        <a class="btn btn-sm" href="#/salaries/${u.id}">Voir ses outils</a>
        ${isAdmin() ? '<button class="btn btn-sm" data-action="edit">Modifier</button>' : ""}
        ${u.id !== state.user.id ? '<button class="btn btn-sm" data-action="reset">Réinitialiser le mot de passe</button>' : ""}
        ${u.id !== state.user.id ? '<button class="btn btn-sm" data-action="reassign">Réaffecter son matériel</button>' : ""}
        ${u.id !== state.user.id && u.is_active ? '<button class="btn btn-sm" data-action="depart">Départ</button>' : ""}
        ${isAdmin() && u.totp_enabled ? '<button class="btn btn-sm" data-action="mfa-reset">Réinitialiser la double authentification</button>' : ""}
        ${isAdmin() && u.id !== state.user.id && !u.username.startsWith("anonyme-") ? '<button class="btn btn-sm" data-action="anonymize">Anonymiser (RGPD)</button>' : ""}
        ${isAdmin() && u.id !== state.user.id ? '<button class="btn btn-sm btn-danger" data-action="delete">Supprimer</button>' : ""}
      </div>
    </div>
  `;
}

async function openUserForm(user, allUsers, onDone) {
  const isEdit = !!user;
  const agencies = await getAgencies(true);
  const admin = isAdmin();

  const myChildRole = CHILD_ROLE[state.user.role];
  const roleOptions = admin
    ? Object.keys(ROLE_LABELS)
    : state.user.role === "directeur_agence"
      ? ["charge_affaires", "magasinier"]
      : myChildRole
        ? [myChildRole]
        : [];
  const canPickRole = admin || roleOptions.length > 1;

  if (!isEdit && roleOptions.length === 0) {
    toast(`${ROLE_LABELS[state.user.role]} ne peut créer aucun compte`, "error");
    return;
  }

  const initialRole = user?.role || roleOptions[0];

  const html = `
    <div class="modal-header">
      <div class="card-title">${isEdit ? "Modifier l'utilisateur" : "Ajouter un utilisateur"}</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <form id="user-form" class="form-grid">
      <div class="field">
        <label>Nom complet</label>
        <input type="text" name="full_name" value="${escapeHtml(user?.full_name || "")}" required/>
      </div>
      <div class="field">
        <label>Identifiant</label>
        <input type="text" name="username" value="${escapeHtml(user?.username || "")}" ${isEdit ? "readonly" : "required"}/>
      </div>
      <div class="field">
        <label>Mot de passe (12 caractères min., une lettre et un chiffre)</label>
        <input type="password" name="password" autocomplete="new-password" placeholder="${isEdit ? "laisser vide pour ne pas changer" : ""}" ${isEdit ? "" : "required"}/>
      </div>
      <div class="field">
        <label>Email</label>
        <input type="email" name="email" value="${escapeHtml(user?.email || "")}"/>
      </div>
      <div class="field">
        <label>Téléphone</label>
        <input type="tel" name="phone" value="${escapeHtml(user?.phone || "")}"/>
      </div>
      <div class="field">
        <label>Rôle</label>
        <select name="role" id="role-select" ${canPickRole ? "" : "disabled"}>
          ${roleOptions.map((r) => `<option value="${r}" ${r === initialRole ? "selected" : ""}>${ROLE_LABELS[r]}</option>`).join("")}
        </select>
      </div>
      <div class="field hidden" id="manager-field">
        <label>Responsable</label>
        <select name="manager_id" id="manager-select"></select>
      </div>
      <div class="field hidden" id="agency-field">
        <label>Agence</label>
        <select name="agency_number">
          ${agencies.map((a) => `<option value="${escapeHtml(a.name)}" ${user?.agency_number === a.name ? "selected" : ""}>${escapeHtml(a.name)}</option>`).join("")}
        </select>
      </div>
      ${
        isEdit
          ? `
      <div class="field">
        <label>Statut</label>
        <select name="is_active">
          <option value="true" ${user.is_active ? "selected" : ""}>Actif</option>
          <option value="false" ${!user.is_active ? "selected" : ""}>Inactif</option>
        </select>
      </div>`
          : ""
      }
      <button type="submit" class="btn btn-primary">${isEdit ? "Enregistrer" : "Ajouter"}</button>
    </form>
  `;

  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      const roleSelect = root.querySelector("#role-select");
      const managerField = root.querySelector("#manager-field");
      const managerSelect = root.querySelector("#manager-select");
      const agencyField = root.querySelector("#agency-field");

      function syncFields() {
        const role = roleSelect.value;
        const parentRole = PARENT_ROLE[role];

        if (parentRole && admin && role !== "magasinier") {
          managerField.classList.remove("hidden");
          const candidates = allUsers.filter((u) => u.role === parentRole);
          managerSelect.innerHTML = candidates
            .map((u) => `<option value="${u.id}" ${user?.manager_id === u.id ? "selected" : ""}>${escapeHtml(u.full_name)}</option>`)
            .join("");
        } else {
          managerField.classList.add("hidden");
        }

        if (admin && (role === "directeur_agence" || role === "magasinier")) {
          agencyField.classList.remove("hidden");
        } else {
          agencyField.classList.add("hidden");
        }
      }

      roleSelect.addEventListener("change", syncFields);
      syncFields();

      root.querySelector("#user-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());

        try {
          if (isEdit) {
            const payload = {
              full_name: data.full_name,
              is_active: data.is_active === "true",
              email: data.email || null,
              phone: data.phone || null,
            };
            if (data.password) payload.password = data.password;
            if (admin) {
              payload.role = data.role;
              if (data.manager_id) payload.manager_id = Number(data.manager_id);
              if (["directeur_agence", "magasinier"].includes(data.role) && data.agency_number) payload.agency_number = data.agency_number;
            }
            await api.patch(`/users/${user.id}`, payload);
          } else {
            const payload = {
              username: data.username,
              full_name: data.full_name,
              password: data.password,
              role: data.role,
            };
            if (data.email) payload.email = data.email;
            if (data.phone) payload.phone = data.phone;
            if (admin) {
              if (data.manager_id) payload.manager_id = Number(data.manager_id);
              if (["directeur_agence", "magasinier"].includes(data.role) && data.agency_number) payload.agency_number = data.agency_number;
            }
            await api.post("/users", payload);
          }
          invalidateUsers();
          toast(isEdit ? "Utilisateur mis à jour" : "Utilisateur créé", "success");
          closeModal();
          onDone();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}
