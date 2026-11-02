import { api } from "./api.js";
import { openModal, closeModal, stateHistoryCard, escapeHtml } from "./ui.js";
import { getAllUsers, getUserName } from "./usersCache.js";

export async function openToolHistory(kind, toolId, toolName) {
  await getAllUsers();
  const history = await api.get(`/state-history?kind=${kind}&tool_id=${toolId}`);

  const body = history.length
    ? history.map((h) => stateHistoryCard(h, getUserName(h.changed_by_id))).join("")
    : `<div class="empty-state">Aucun historique pour le moment.</div>`;

  openModal(`
    <div class="modal-header">
      <div class="card-title">Historique — ${escapeHtml(toolName)}</div>
      <button class="btn btn-ghost btn-sm" id="history-close">Fermer</button>
    </div>
    <div class="modal-body">${body}</div>
  `, {
    onMount: (root) => {
      root.querySelector("#history-close").addEventListener("click", closeModal);
    },
  });
}
