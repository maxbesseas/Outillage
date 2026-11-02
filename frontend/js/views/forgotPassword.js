import { api, ApiError } from "../api.js";
import { toast, escapeHtml } from "../ui.js";

export async function renderForgotPassword(app) {
  app.innerHTML = `
    <div class="login-screen">
      <div class="login-banner"><h1>Mot de passe oublié</h1></div>
      <div class="card login-card">
        <form id="forgot-form" class="form-grid">
          <p class="card-sub">Saisissez votre identifiant ou votre adresse email. Si un compte correspond et possède une adresse email, un lien de réinitialisation valable 30 minutes vous sera envoyé.</p>
          <div class="field">
            <label>Identifiant ou email</label>
            <input type="text" name="identifier" autocomplete="username" required/>
          </div>
          <button type="submit" class="btn btn-primary btn-block" id="forgot-submit">Envoyer le lien</button>
          <a href="#/login" class="login-link">Retour à la connexion</a>
        </form>
        <p class="card-sub">Sans adresse email enregistrée, demandez à votre responsable ou à l'administrateur de réinitialiser votre mot de passe.</p>
      </div>
    </div>
  `;

  const form = document.getElementById("forgot-form");
  const submit = document.getElementById("forgot-submit");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const identifier = new FormData(form).get("identifier");
    submit.disabled = true;
    try {
      const res = await api.post("/auth/forgot-password", { identifier });
      form.innerHTML = `<p class="card-sub">${escapeHtml(res.detail)}</p><a href="#/login" class="login-link">Retour à la connexion</a>`;
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur", "error");
      submit.disabled = false;
    }
  });
}
