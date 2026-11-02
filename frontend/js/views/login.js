import { api, ApiError } from "../api.js";
import { setSession } from "../state.js";
import { navigate } from "../router.js";
import { toast, wireImageFallbacks } from "../ui.js";

export async function renderLogin(app) {
  app.innerHTML = `
    <div class="login-screen">
      <div class="login-banner">
        <h1>Gestion Outillage</h1>
      </div>
      <div class="card login-card">
        <div class="login-logo">
          <img src="/icons/fauche-logo-full.png" alt="Fauché" data-fallback-hide/>
        </div>
        <form id="login-form" class="form-grid">
          <div class="field">
            <label>Identifiant</label>
            <input type="text" name="username" autocomplete="username" required/>
          </div>
          <div class="field">
            <label>Mot de passe</label>
            <input type="password" name="password" autocomplete="current-password" required/>
          </div>
          <button type="submit" class="btn btn-primary btn-block" id="login-submit">Se connecter</button>
          <a href="#/mot-de-passe-oublie" class="login-link">Mot de passe oublié ?</a>
        </form>
      </div>
    </div>
  `;
  wireImageFallbacks(app);

  const form = document.getElementById("login-form");
  const submitBtn = document.getElementById("login-submit");

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(form).entries());
    submitBtn.disabled = true;
    try {
      const res = await api.post("/auth/login", data);
      setSession(res.access_token, res.user, res.refresh_token);
      navigate("/");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur de connexion", "error");
    } finally {
      submitBtn.disabled = false;
    }
  });
}
