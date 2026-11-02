import { api } from "../api.js";
import { escapeHtml, formatDateTime } from "../ui.js";

let days = 30;

export async function renderAssistantInsights(app) {
  const ins = await api.get(`/assistant/insights?days=${days}`);
  app.innerHTML = `
    <div class="section-header"><h1>Assistant — suivi</h1>
      <select id="ai-days">${[7, 30, 90].map((d) => `<option value="${d}" ${d === days ? "selected" : ""}>${d} derniers jours</option>`).join("")}</select></div>
    <div class="stat-grid">
      <div class="stat-tile"><div class="stat-value">${ins.messages}</div><div class="stat-label">Messages</div></div>
      <div class="stat-tile"><div class="stat-value">${ins.by_source.claude || 0}</div><div class="stat-label">Réponses IA (${ins.by_source.local || 0} en mode documentation)</div></div>
      <div class="stat-tile"><div class="stat-value">${ins.feedback.up} / ${ins.feedback.down}</div><div class="stat-label">Utile / pas utile</div></div>
      <div class="stat-tile"><div class="stat-value">${ins.tokens.toLocaleString("fr-FR")}</div><div class="stat-label">Jetons consommés</div></div>
    </div>
    <h3>Questions sans réponse (${ins.unanswered.length})</h3>
    ${ins.unanswered.map((q) => `<div class="card-sub">${escapeHtml(q.user || "-")} · ${formatDateTime(q.created_at)} — « ${escapeHtml(q.question)} »</div>`).join("") || '<div class="card-sub">Aucune.</div>'}
    <h3>Réponses jugées pas utiles (${ins.disliked.length})</h3>
    ${ins.disliked.map((d) => `<div class="card"><div class="card-sub">Q : ${escapeHtml(d.question)}</div><div class="card-sub">R : ${escapeHtml(d.answer)}</div>${d.comment ? `<div class="card-sub">Commentaire : ${escapeHtml(d.comment)}</div>` : ""}</div>`).join("") || '<div class="card-sub">Aucune.</div>'}`;

  document.getElementById("ai-days").addEventListener("change", (e) => {
    days = Number(e.target.value);
    renderAssistantInsights(app);
  });
}
