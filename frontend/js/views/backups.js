import { api, ApiError } from "../api.js";
import { escapeHtml, formatDateTime, toast, openModal, closeModal } from "../ui.js";

const fail = (err) => toast(err instanceof ApiError ? err.message : "Erreur", "error");
const size = (n) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} Mo` : `${Math.max(1, Math.round(n / 1024))} Ko`);

export async function renderBackups(app) {
  const [backups, tasks] = await Promise.all([api.get("/admin/backups"), api.get("/admin/excel-sync")]);
  const pending = tasks.filter((t) => t.status === "pending");

  app.innerHTML = `
    <div class="section-header"><h1>Sauvegardes</h1><button class="btn btn-primary btn-sm" id="bk-create">Sauvegarder maintenant</button></div>
    <p class="card-sub">Une sauvegarde complète (base + fichiers téléversés) est créée chaque jour, l'heure et le nombre conservé se règlent dans les paramètres. Elle contient des données personnelles : conservez-la en lieu sûr.</p>
    ${backups.map((b) => `<div class="card" data-name="${escapeHtml(b.name)}"><div class="card-row"><div class="card-title">${escapeHtml(b.name)}</div><span class="card-sub">${size(b.size)}</span></div>
      <div class="card-sub">${escapeHtml(formatDateTime(b.created_at))}</div>
      <div class="card-actions"><button class="btn btn-sm" data-act="verify">Vérifier</button><button class="btn btn-sm" data-act="download">Télécharger</button><button class="btn btn-sm btn-danger" data-act="delete">Supprimer</button></div></div>`).join("") || '<div class="empty-state">Aucune sauvegarde.</div>'}
    <h3>Restauration</h3>
    <div class="card-sub">La restauration se fait volontairement hors de l'application : arrêtez le serveur, dézippez la sauvegarde, remplacez <code>backend/outillage.db</code> par <code>outillage.db</code> de l'archive et le dossier <code>backend/uploads/</code> par <code>uploads/</code>, puis relancez. Voir « DOCUMENTATION_COMPLETE.md », section Sauvegardes.</div>
    <h3>Synchronisation Excel en attente (${pending.length})</h3>
    ${pending.map((t) => `<div class="card-sub">Outil n°${t.tool_id} (${escapeHtml(t.action)}) — agence ${escapeHtml(t.agency_number || "-")} — ${t.attempts} tentative(s) — ${escapeHtml(t.last_error || "")}</div>`).join("") || '<div class="card-sub">Rien en attente : les classeurs Excel sont à jour.</div>'}
    <div class="card-actions"><button class="btn btn-sm" id="xl-retry">Réessayer maintenant</button></div>`;

  document.getElementById("bk-create").addEventListener("click", async () => {
    try {
      await api.post("/admin/backups");
      toast("Sauvegarde créée", "success");
      renderBackups(app);
    } catch (err) {
      fail(err);
    }
  });
  document.getElementById("xl-retry").addEventListener("click", async () => {
    try {
      const r = await api.post("/admin/excel-sync/retry");
      toast(`${r.done} mise(s) à jour rejouée(s), ${r.pending} en attente`, "success");
      renderBackups(app);
    } catch (err) {
      fail(err);
    }
  });
  app.querySelectorAll("[data-act]").forEach((btn) =>
    btn.addEventListener("click", async () => {
      const name = btn.closest(".card").dataset.name;
      try {
        if (btn.dataset.act === "download") await api.download(`/admin/backups/${encodeURIComponent(name)}`, name);
        else if (btn.dataset.act === "verify") {
          const v = await api.get(`/admin/backups/${encodeURIComponent(name)}/verify`);
          openModal(
            `<div class="modal-header"><div class="card-title">Vérification</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
            <div class="alert-block ${v.ok ? "ok-block" : ""}"><strong>${escapeHtml(v.message)}</strong></div>
            ${v.counts ? `<div class="card-sub">${Object.entries(v.counts).map(([k, n]) => `${escapeHtml(k)} : ${n}`).join(" · ")} · ${v.upload_files} fichier(s) · schéma v${v.schema_version ?? "?"}</div>` : ""}`,
            { onMount: (root) => root.querySelector("#c").addEventListener("click", closeModal) }
          );
        } else {
          openModal(
            `<div class="modal-header"><div class="card-title">Supprimer cette sauvegarde ?</div></div><div class="card-actions"><button class="btn btn-danger" id="yes">Supprimer</button><button class="btn" id="no">Annuler</button></div>`,
            {
              onMount: (root) => {
                root.querySelector("#no").addEventListener("click", closeModal);
                root.querySelector("#yes").addEventListener("click", async () => {
                  try {
                    await api.delete(`/admin/backups/${encodeURIComponent(name)}`);
                    closeModal();
                    renderBackups(app);
                  } catch (err) {
                    fail(err);
                  }
                });
              },
            }
          );
        }
      } catch (err) {
        fail(err);
      }
    })
  );
}
