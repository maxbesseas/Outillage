import { api, ApiError } from "../api.js";
import { escapeHtml, toast } from "../ui.js";

const GROUPS = {
  alert: "Alertes et rappels",
  inspection: "Contrôles périodiques",
  calibration: "Étalonnage",
  qualification: "Habilitations",
  loan: "Réservations",
  photo: "Photos",
  exit: "Sortie de parc",
  cost: "Coûts d'usage",
  assistant: "Assistant IA",
};

const BOOLEAN_KEYS = new Set([
  "calibration.block_reservation",
  "qualification.block",
  "photo.required_on_bad_return",
  "photo.required_on_nonconform",
  "exit.requires_approval",
  "exit.release_code",
]);

export async function renderAppSettingsSection(container) {
  const settings = await api.get("/settings/app");
  const groups = {};
  for (const s of settings) {
    const prefix = s.key.split(".")[0];
    (groups[prefix] = groups[prefix] || []).push(s);
  }

  container.innerHTML = `
    <h3>Réglages avancés</h3>
    <p class="card-sub">Les valeurs par défaut des périodicités sont à valider par le responsable sécurité de l'entreprise : aucune valeur réglementaire n'est imposée par l'application.</p>
    <form id="app-settings-form" class="form-grid">
      ${Object.entries(groups)
        .map(
          ([prefix, items]) => `
        <details class="card settings-group">
          <summary><strong>${escapeHtml(GROUPS[prefix] || prefix)}</strong></summary>
          ${items
            .map(
              (s) => `
            <div class="field">
              <label for="as-${escapeHtml(s.key)}">${escapeHtml(s.description)}</label>
              ${
                BOOLEAN_KEYS.has(s.key)
                  ? `<select id="as-${escapeHtml(s.key)}" data-key="${escapeHtml(s.key)}">
                      <option value="true" ${s.value === "true" ? "selected" : ""}>Oui</option>
                      <option value="false" ${s.value !== "true" ? "selected" : ""}>Non</option>
                    </select>`
                  : `<input id="as-${escapeHtml(s.key)}" data-key="${escapeHtml(s.key)}" value="${escapeHtml(s.value)}"/>`
              }
              <span class="card-sub">Défaut : ${escapeHtml(s.default)}</span>
            </div>`
            )
            .join("")}
        </details>`
        )
        .join("")}
      <button type="submit" class="btn btn-primary">Enregistrer les réglages avancés</button>
    </form>
  `;

  container.querySelector("#app-settings-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const values = {};
    container.querySelectorAll("[data-key]").forEach((el) => {
      values[el.dataset.key] = el.value;
    });
    try {
      await api.patch("/settings/app", { values });
      toast("Réglages enregistrés", "success");
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur", "error");
    }
  });
}
