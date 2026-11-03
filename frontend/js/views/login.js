import { api, ApiError } from "../api.js";
import { setSession } from "../state.js";
import { navigate } from "../router.js";
import { toast } from "../ui.js";
import { TOOL_BOARD_SVG } from "./toolBoard.js";

const MICROSOFT_ERRORS = {
  no_account: "Aucun compte ne correspond à ce compte Microsoft. Demandez à votre administrateur de créer votre compte avec cette adresse e-mail.",
  failed: "La connexion Microsoft n'a pas abouti. Réessayez ou utilisez votre identifiant.",
};

const MICROSOFT_LOGO = `
  <svg viewBox="0 0 21 21" width="20" height="20" aria-hidden="true">
    <rect x="1" y="1" width="9" height="9" fill="#f25022"/>
    <rect x="11" y="1" width="9" height="9" fill="#7fba00"/>
    <rect x="1" y="11" width="9" height="9" fill="#00a4ef"/>
    <rect x="11" y="11" width="9" height="9" fill="#ffb900"/>
  </svg>`;

async function microsoftEnabled() {
  try {
    const res = await fetch("/auth/microsoft/config");
    return res.ok && (await res.json()).enabled === true;
  } catch {
    return false;
  }
}

// Le code à usage unique quitte l'adresse de la page avant même d'être échangé.
async function finishMicrosoftLogin(code) {
  history.replaceState(null, "", "#/login");
  try {
    const res = await api.post("/auth/refresh", { refresh_token: code });
    setSession(res.access_token, res.user, res.refresh_token);
    navigate("/");
    return true;
  } catch {
    toast(MICROSOFT_ERRORS.failed, "error");
    return false;
  }
}

export async function renderLogin(app, { query } = {}) {
  const code = query?.get("sso");
  if (code && (await finishMicrosoftLogin(code))) return;

  const errorMessage = MICROSOFT_ERRORS[query?.get("sso_error")];
  if (query?.has("sso_error")) history.replaceState(null, "", "#/login");

  app.innerHTML = `
    <div class="lp">
      <section class="lp-board">
        <div class="lp-board-text">
          <img class="lp-logo" src="/icons/fauche-logo-full.png" alt="Fauché" width="165" height="148"/>
          <h1>Chaque outil à sa place.</h1>
          <p>Prêts, retours, contrôles et inventaire de l'outillage Fauché, agence par agence.</p>
        </div>
        ${TOOL_BOARD_SVG}
      </section>
      <section class="lp-access" aria-label="Connexion">
        <div class="lp-access-inner">
          <h2>Connexion</h2>
          ${errorMessage ? `<p class="lp-error" role="alert">${errorMessage}</p>` : ""}
          <div id="lp-microsoft" class="lp-microsoft" hidden>
            <a class="lp-microsoft-btn" href="/auth/microsoft/login">${MICROSOFT_LOGO}<span>Se connecter avec Microsoft</span></a>
            <p class="lp-note">Votre compte doit d'abord être créé par un administrateur.</p>
            <div class="lp-or"><span>ou</span></div>
          </div>
          <form id="login-form" class="lp-form">
            <div class="field">
              <label for="login-username">Identifiant</label>
              <input id="login-username" type="text" name="username" autocomplete="username" required/>
            </div>
            <div class="field">
              <label for="login-password">Mot de passe</label>
              <input id="login-password" type="password" name="password" autocomplete="current-password" required/>
            </div>
            <div class="field" id="login-otp-field" hidden>
              <label for="login-otp">Code de vérification (application d'authentification)</label>
              <input id="login-otp" type="text" name="otp" inputmode="numeric" autocomplete="one-time-code" maxlength="6"/>
            </div>
            <button type="submit" class="btn btn-primary btn-block" id="login-submit">Se connecter</button>
            <a href="#/mot-de-passe-oublie" class="login-link">Mot de passe oublié ?</a>
          </form>
        </div>
      </section>
    </div>
  `;

  microsoftEnabled().then((isEnabled) => {
    const block = document.getElementById("lp-microsoft");
    if (block) block.hidden = !isEnabled;
  });

  const form = document.getElementById("login-form");
  const submitBtn = document.getElementById("login-submit");

  let submitting = false;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (submitting) return;
    submitting = true;
    const data = Object.fromEntries(new FormData(form).entries());
    if (!data.otp) delete data.otp;
    submitBtn.disabled = true;
    try {
      const res = await api.post("/auth/login", data);
      setSession(res.access_token, res.user, res.refresh_token);
      navigate("/");
    } catch (err) {
      if (err instanceof ApiError && err.message === "Saisissez le code de vérification") {
        document.getElementById("login-otp-field").hidden = false;
        document.getElementById("login-otp").focus();
      }
      toast(err instanceof ApiError ? err.message : "Erreur de connexion", "error");
    } finally {
      submitting = false;
      submitBtn.disabled = false;
    }
  });
}
