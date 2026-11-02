import { api, ApiError } from "./api.js";
import { escapeHtml, toast, openModal, closeModal } from "./ui.js";
import { compressImage } from "./images.js";
import { queueOrSend } from "./offlineQueue.js";

const CATEGORIES = [
  ["panne", "Panne"],
  ["casse", "Casse"],
  ["usure", "Usure"],
  ["accessoire_manquant", "Accessoire manquant"],
  ["perte", "Perte"],
  ["vol", "Vol"],
  ["autre", "Autre"],
];
const SEVERITIES = [
  ["faible", "Faible"],
  ["moyenne", "Moyenne"],
  ["haute", "Haute"],
  ["critique", "Critique"],
];

/** Signalement rapide d'un problème (crée un ticket de maintenance ; utilisable hors ligne). */
export function openReportProblem(kind, tool, onDone) {
  openModal(
    `
    <div class="modal-header">
      <div class="card-title">Signaler un problème — ${escapeHtml(tool.name)}</div>
      <button class="btn btn-ghost btn-sm" id="rp-close">Fermer</button>
    </div>
    <form id="rp-form" class="form-grid">
      <div class="field"><label>Nature du problème</label>
        <select name="category">${CATEGORIES.map(([v, l]) => `<option value="${v}">${l}</option>`).join("")}</select></div>
      <div class="field"><label>Gravité</label>
        <select name="severity">${SEVERITIES.map(([v, l]) => `<option value="${v}" ${v === "moyenne" ? "selected" : ""}>${l}</option>`).join("")}</select></div>
      <div class="field"><label>Description</label><textarea name="description" rows="3" placeholder="Que s'est-il passé ?"></textarea></div>
      <div class="field"><label>Photo (recommandée)</label><input type="file" name="photo" accept="image/*" capture="environment"/></div>
      <button type="submit" class="btn btn-primary btn-block">Envoyer le signalement</button>
    </form>`,
    {
      onMount: (root) => {
        root.querySelector("#rp-close").addEventListener("click", closeModal);
        root.querySelector("#rp-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          const photo = f.get("photo");
          try {
            const result = await queueOrSend({
              label: `Signalement : ${tool.name}`,
              method: "POST",
              path: "/maintenance-tickets",
              body: {
                tool_kind: kind,
                tool_id: tool.id,
                category: f.get("category"),
                severity: f.get("severity"),
                description: f.get("description") || null,
                photo_attached: !!(photo && photo.size),
              },
              followUp:
                photo && photo.size
                  ? { path: "/maintenance-tickets/{id}/attachments?kind=photo", file: await compressImage(photo) }
                  : null,
            });
            toast(result.queued ? "Signalement enregistré, il sera envoyé au retour du réseau" : "Signalement envoyé", "success");
            closeModal();
            if (onDone) onDone(result);
          } catch (err) {
            toast(err instanceof ApiError ? err.message : "Erreur", "error");
          }
        });
      },
    }
  );
}
