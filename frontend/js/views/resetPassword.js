import { api, ApiError } from "../api.js";
import { toast, escapeHtml } from "../ui.js";

export async function renderResetPassword(app, params) {
  const token = params.query.get("token") || "";

  app.innerHTML = `
    <div class="login-screen">
      <div class="login-banner"><h1>Nouveau mot de passe</h1></div>
      <div class="card login-card">
        ${
          token
            ? `<form id="reset-form" class="form-grid">
          <div class="field">
            <label>Nouveau mot de passe</label>
            <input type="password" name="password" autocomplete="new-password" required minlength="8"/>
          </div>
          <div class="field">
            <label>Confirmer</label>
            <input type="password" name="confirm" autocomplete="new-password" required minlength="8"/>
          </div>
          <p class="card-sub">Au moins 8 caractères, dont une lettre et un chiffre.</p>
          <button type="submit" class="btn btn-primary btn-block" id="reset-submit">Enregistrer</button>
        </form>`
            : `<p class="card-sub">Lien invalide : aucun jeton fourni.</p><a href="#/login" class="login-link">Retour à la connexion</a>`
        }
      </div>
    </div>
  `;

  const form = document.getElementById("reset-form");
  if (!form) return;
  const submit = document.getElementById("reset-submit");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    if (data.password !== data.confirm) {
      toast("Les deux mots de passe ne correspondent pas", "error");
      return;
    }
    submit.disabled = true;
    try {
      const res = await api.post("/auth/reset-password", { token, new_password: data.password });
      form.innerHTML = `<p class="card-sub">${escapeHtml(res.detail)}</p><a href="#/login" class="btn btn-primary btn-block">Se connecter</a>`;
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur", "error");
      submit.disabled = false;
    }
  });
}
