import { api, ApiError } from "../api.js";
import { escapeHtml, formatDateTime, toast } from "../ui.js";

const STATUS_BADGE = {
  ok: ["green", "Réussie"],
  error: ["red", "Échec"],
  running: ["orange", "En cours"],
  skipped: ["gray", "Ignorée"],
};

function interval(seconds) {
  if (seconds % 86400 === 0) return `toutes les ${seconds / 86400 === 1 ? "24 h" : `${seconds / 86400} jours`}`;
  if (seconds % 3600 === 0) return `toutes les ${seconds / 3600} h`;
  return `toutes les ${Math.round(seconds / 60)} min`;
}

export async function renderJobs(app) {
  const jobs = await api.get("/admin/jobs");

  app.innerHTML = `
    <div class="section-header">
      <h1>Tâches planifiées</h1>
      <div class="section-links"><a href="#/parametres">Paramètres</a></div>
    </div>
    <p class="card-sub">Ces tâches s'exécutent automatiquement au démarrage du serveur (désactivable avec OUTILLAGE_SCHEDULER=off) et peuvent aussi être déclenchées par un planificateur externe via l'endpoint protégé par clé.</p>
    ${jobs
      .map((j) => {
        const [color, label] = STATUS_BADGE[j.last_status] || ["gray", "Jamais exécutée"];
        return `
        <div class="card" data-job="${escapeHtml(j.name)}">
          <div class="card-row">
            <div class="card-title">${escapeHtml(j.description)}</div>
            <span class="badge badge-${color}"><span class="dot"></span>${label}</span>
          </div>
          <div class="card-meta">
            <span>${escapeHtml(j.name)}</span>
            <span>${interval(j.interval_seconds)}</span>
            <span>Dernier passage : ${j.last_started_at ? escapeHtml(formatDateTime(j.last_started_at)) : "-"}</span>
          </div>
          ${j.last_message ? `<div class="card-sub">${escapeHtml(j.last_message)}</div>` : ""}
          <div class="card-actions"><button class="btn btn-sm" data-action="run">Lancer maintenant</button></div>
        </div>`;
      })
      .join("")}
  `;

  app.querySelectorAll("[data-job]").forEach((card) => {
    card.querySelector('[data-action="run"]').addEventListener("click", async (e) => {
      e.target.disabled = true;
      try {
        const res = await api.post(`/admin/jobs/${card.dataset.job}/run`);
        toast(`${res.status === "ok" ? "Tâche exécutée" : "Tâche : " + res.status} — ${res.message}`, res.status === "ok" ? "success" : "error");
        renderJobs(app);
      } catch (err) {
        toast(err instanceof ApiError ? err.message : "Erreur", "error");
        e.target.disabled = false;
      }
    });
  });
}
