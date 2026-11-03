import { api, ApiError } from "../api.js";
import { setSession, state } from "../state.js";
import { navigate } from "../router.js";
import { escapeHtml, formatDateTime, toast } from "../ui.js";

export async function renderCharter(app) {
  const charter = await api.get("/charter");
  const pending = charter.accepted_version < charter.version;

  app.innerHTML = `
    <div class="section-header"><h1>${escapeHtml(charter.title)}</h1></div>
    ${pending ? `<div class="alert-block warning"><strong>Lecture et acceptation obligatoires</strong>
      <div class="card-sub">Acceptez cette charte pour accéder à l'application.</div></div>` : ""}
    ${charter.sections
      .map(
        (s) => `<div class="card"><div class="card-title">${escapeHtml(s.title)}</div>
          ${s.items.map((item) => `<p class="card-sub">${escapeHtml(item)}</p>`).join("")}</div>`
      )
      .join("")}
    ${
      pending
        ? `<form id="charter-form" class="card form-grid">
            <label><input type="checkbox" name="agree" required/> J'ai lu la charte (version ${Number(charter.version)}) et je m'engage à la respecter.</label>
            <button type="submit" class="btn btn-primary">Accepter et continuer</button>
          </form>`
        : `<p class="card-sub">Acceptée le ${escapeHtml(formatDateTime(charter.accepted_at))} (version ${Number(charter.accepted_version)}).</p>`
    }
  `;

  const form = document.getElementById("charter-form");
  if (!form) return;
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const user = await api.post("/charter/accept", { version: charter.version });
      setSession(state.token, user);
      toast("Charte acceptée", "success");
      navigate("/");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur", "error");
    }
  });
}
