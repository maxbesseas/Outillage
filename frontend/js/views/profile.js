import { api, ApiError } from "../api.js";
import { state, setSession, mustChangePassword } from "../state.js";
import { ROLE_LABELS } from "../roles.js";
import { escapeHtml, toast } from "../ui.js";
import { navigate } from "../router.js";
import { pushSupported, currentSubscription, enablePush, disablePush } from "../push.js";
import { getTheme, setTheme } from "../theme.js";

export async function renderProfile(app) {
  const me = await api.get("/auth/me");
  setSession(state.token, me);
  const forced = mustChangePassword();
  const prefs = forced ? [] : await api.get("/notifications/preferences");
  const pushOn = !forced && pushSupported() ? !!(await currentSubscription()) : false;

  app.innerHTML = `
    <div class="section-header"><h1>Mon profil</h1></div>

    ${
      forced
        ? `<div class="alert-block warning"><strong>Changement de mot de passe obligatoire</strong>
           <div class="card-sub">Votre mot de passe est temporaire ou celui par défaut. Choisissez-en un nouveau pour continuer.</div></div>`
        : ""
    }

    <div class="card">
      <div class="card-title">${escapeHtml(me.full_name)}</div>
      <div class="card-sub">@${escapeHtml(me.username)}</div>
      <div class="card-meta">
        <span>${escapeHtml(ROLE_LABELS[me.role] || me.role)}</span>
        <span>Agence : ${escapeHtml(me.agency_number || "-")}</span>
      </div>
    </div>

    ${
      forced
        ? ""
        : `<h3>Coordonnées</h3>
    <form id="contact-form" class="form-grid card">
      <div class="field">
        <label>Email (utilisé pour la réinitialisation du mot de passe)</label>
        <input type="email" name="email" value="${escapeHtml(me.email || "")}" autocomplete="email"/>
      </div>
      <div class="field">
        <label>Téléphone</label>
        <input type="tel" name="phone" value="${escapeHtml(me.phone || "")}" autocomplete="tel" inputmode="tel"/>
      </div>
      <button type="submit" class="btn btn-primary">Enregistrer</button>
    </form>`
    }

    <h3>Mot de passe</h3>
    <form id="password-form" class="form-grid card">
      <div class="field">
        <label>Mot de passe actuel</label>
        <input type="password" name="current" autocomplete="current-password" required/>
      </div>
      <div class="field">
        <label>Nouveau mot de passe</label>
        <input type="password" name="password" autocomplete="new-password" required minlength="8"/>
      </div>
      <div class="field">
        <label>Confirmer le nouveau mot de passe</label>
        <input type="password" name="confirm" autocomplete="new-password" required minlength="8"/>
      </div>
      <p class="card-sub">Au moins 8 caractères, dont une lettre et un chiffre. Le changement déconnecte vos autres appareils.</p>
      <button type="submit" class="btn btn-primary">Changer le mot de passe</button>
    </form>

    ${
      forced
        ? ""
        : `<h3>Apparence</h3>
    <div class="card">
      <div class="card-row"><div><div class="card-title">Thème</div><div class="card-sub">Suivre l'appareil, ou forcer le mode clair / sombre.</div></div>
        <select id="theme-select">
          <option value="system">Automatique (système)</option>
          <option value="light">Clair</option>
          <option value="dark">Sombre</option>
        </select>
      </div>
    </div>
    <h3>Agenda externe</h3>
    <div class="card" id="calendar-card">
      <div class="card-sub">Ajoutez vos réservations et vos échéances de retour à Outlook, Google Agenda ou Apple Calendrier (lecture seule).
        Le lien est secret : ne le partagez pas ; vous pouvez le révoquer à tout moment.</div>
      <div id="calendar-url" class="card-sub"></div>
      <div class="card-actions">
        <button class="btn btn-sm btn-primary" id="cal-generate">Créer / renouveler le lien</button>
        <button class="btn btn-sm" id="cal-copy">Copier</button>
        <button class="btn btn-sm btn-danger" id="cal-revoke">Révoquer</button>
      </div>
    </div>
    <h3>Notifications</h3>
    <div class="card">
      <div class="card-row">
        <div><div class="card-title">Notifications sur cet appareil</div>
          <div class="card-sub">${pushSupported() ? "Recevez les alertes même application fermée (HTTPS requis)." : "Non disponible sur cet appareil ou ce navigateur."}</div></div>
        ${pushSupported() ? `<button class="btn btn-sm ${pushOn ? "" : "btn-primary"}" id="push-toggle">${pushOn ? "Désactiver" : "Activer"}</button>` : ""}
      </div>
    </div>
    <form id="prefs-form" class="card">
      <table class="simple-table pref-table">
        <thead><tr><th>Alerte</th><th>Centre</th><th>Email</th><th>Push</th></tr></thead>
        <tbody>
          ${prefs
            .map(
              (p) => `<tr data-type="${escapeHtml(p.type)}">
              <td>${escapeHtml(p.label || p.type)}</td>
              <td><input type="checkbox" name="in_app" ${p.in_app ? "checked" : ""} aria-label="Centre d'alertes"/></td>
              <td><input type="checkbox" name="email" ${p.email ? "checked" : ""} aria-label="Email"/></td>
              <td><input type="checkbox" name="push" ${p.push ? "checked" : ""} aria-label="Push"/></td>
            </tr>`
            )
            .join("")}
        </tbody>
      </table>
      <p class="card-sub">Les emails sont regroupés en un seul message quotidien. Il faut une adresse email dans vos coordonnées.</p>
      <button type="submit" class="btn btn-primary">Enregistrer les préférences</button>
    </form>
    <h3>Mes données personnelles</h3>
    <div class="card"><div class="card-row"><div><div class="card-title">Télécharger mes données</div>
      <div class="card-sub">Profil, réservations, signalements, contrôles et notifications vous concernant (fichier JSON).</div></div>
      <button class="btn btn-sm" id="gdpr-export">Télécharger</button></div></div>`
    }
  `;

  document.getElementById("gdpr-export")?.addEventListener("click", async () => {
    try {
      const data = await api.get(`/gdpr/export/${me.id}`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = `mes-donnees-${me.username}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur", "error");
    }
  });

  const themeSelect = document.getElementById("theme-select");
  if (themeSelect) {
    themeSelect.value = getTheme();
    themeSelect.addEventListener("change", () => setTheme(themeSelect.value));
  }

  const contactForm = document.getElementById("contact-form");
  if (contactForm) {
    contactForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(contactForm).entries());
      try {
        const updated = await api.patch("/auth/me", { email: data.email || null, phone: data.phone || null });
        setSession(state.token, updated);
        toast("Coordonnées enregistrées", "success");
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Erreur", "error");
      }
    });
  }

  const calUrl = document.getElementById("calendar-url");
  if (calUrl) {
    const paint = (url) => (calUrl.textContent = url || "Aucun lien actif.");
    api.get("/calendar/token").then((r) => paint(r.url)).catch(() => paint(null));
    document.getElementById("cal-generate").addEventListener("click", async () => paint((await api.post("/calendar/token")).url));
    document.getElementById("cal-revoke").addEventListener("click", async () => {
      await api.delete("/calendar/token");
      paint(null);
    });
    document.getElementById("cal-copy").addEventListener("click", async () => {
      const url = calUrl.textContent;
      if (!url.startsWith("http")) return toast("Créez d'abord un lien", "error");
      try {
        await navigator.clipboard.writeText(url);
        toast("Lien copié", "success");
      } catch {
        toast("Copie impossible : sélectionnez le lien manuellement", "error");
      }
    });
  }

  const prefsForm = document.getElementById("prefs-form");
  if (prefsForm) {
    prefsForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const items = [...prefsForm.querySelectorAll("tbody tr")].map((row) => ({
        type: row.dataset.type,
        in_app: row.querySelector('[name="in_app"]').checked,
        email: row.querySelector('[name="email"]').checked,
        push: row.querySelector('[name="push"]').checked,
      }));
      try {
        await api.put("/notifications/preferences", items);
        toast("Préférences enregistrées", "success");
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Erreur", "error");
      }
    });
  }

  const pushToggle = document.getElementById("push-toggle");
  if (pushToggle) {
    pushToggle.addEventListener("click", async () => {
      try {
        if (pushOn) await disablePush();
        else await enablePush();
        renderProfile(app);
      } catch (err) {
        toast(err.message || "Erreur", "error");
      }
    });
  }

  document.getElementById("password-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    const data = Object.fromEntries(new FormData(form).entries());
    if (data.password !== data.confirm) {
      toast("Les deux mots de passe ne correspondent pas", "error");
      return;
    }
    try {
      const res = await api.post("/auth/change-password", { current_password: data.current, new_password: data.password });
      setSession(res.access_token, res.user, res.refresh_token);
      toast("Mot de passe modifié", "success");
      navigate("/");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur", "error");
    }
  });
}
