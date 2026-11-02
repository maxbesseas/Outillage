import { api, ApiError } from "./api.js";
import { escapeHtml, formatDateTime, loanStatusBadge, toast, openModal, closeModal, toDatetimeLocal, confirmDialog, promptDialog } from "./ui.js";
import { state, isManager } from "./state.js";
import { getUserName } from "./usersCache.js";
import { openToolHistory } from "./toolHistory.js";
import { openSignaturePad } from "./signaturePad.js";
import { compressImage } from "./images.js";

const EVENT_LABELS = {
  created: "Créée",
  modified: "Modifiée",
  extended: "Prolongée",
  checkout: "Outil retiré",
  returned: "Rendue",
  cancelled: "Annulée",
  approved: "Validée",
  rejected: "Refusée",
  no_show: "Annulée automatiquement",
};

const fail = (err) => toast(err instanceof ApiError ? err.message : "Erreur", "error");

export function openReturnForm(loan, onDone) {
  openModal(
    `
    <div class="modal-header">
      <div class="card-title">Retour de réservation</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <form id="return-form" class="form-grid">
      <div class="field">
        <label>État constaté au retour (0-5)</label>
        <input type="number" name="state_after" min="0" max="5" value="${loan.state_before ?? 5}" required inputmode="numeric"/>
      </div>
      <label><input type="checkbox" name="accessories_ok" checked/> Accessoires complets (batterie, chargeur, coffret…)</label>
      <div class="field"><label>Commentaire</label><textarea name="comment_return" rows="2"></textarea></div>
      <div class="field"><label>Photo (obligatoire si l'outil est rendu en mauvais état, selon les réglages)</label>
        <input type="file" name="photo" accept="image/*" capture="environment"/></div>
      <button type="submit" class="btn btn-primary">Confirmer le retour</button>
    </form>`,
    {
      onMount: (root) => {
        root.querySelector("#form-close").addEventListener("click", closeModal);
        root.querySelector("#return-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          const file = f.get("photo");
          const hasPhoto = !!(file && file.size);
          try {
            await api.post(`/loans/${loan.id}/return`, {
              state_after: Number(f.get("state_after")),
              comment_return: f.get("comment_return") || null,
              photo_attached: hasPhoto,
              accessories_ok: f.has("accessories_ok"),
            });
            if (hasPhoto) await api.upload(`/loans/${loan.id}/return/photo`, await compressImage(file));
            toast("Retour enregistré", "success");
            closeModal();
            onDone();
          } catch (err) {
            fail(err);
          }
        });
      },
    }
  );
}

function openExtendForm(loan, onDone) {
  openModal(
    `
    <div class="modal-header"><div class="card-title">Prolonger la réservation</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    <form id="ext-form" class="form-grid">
      <div class="field"><label>Nouvelle fin</label>
        <input type="datetime-local" name="new_end" value="${toDatetimeLocal(new Date(new Date(loan.end_datetime_planned).getTime() + 3600 * 1000 * 2))}" required/></div>
      <div id="ext-alternatives"></div>
      <button type="submit" class="btn btn-primary">Prolonger</button>
    </form>`,
    {
      onMount: (root) => {
        root.querySelector("#c").addEventListener("click", closeModal);
        root.querySelector("#ext-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const end = new Date(new FormData(e.target).get("new_end")).toISOString();
          try {
            await api.post(`/loans/${loan.id}/extend`, { new_end: end });
            toast("Réservation prolongée", "success");
            closeModal();
            onDone();
          } catch (err) {
            fail(err);
            try {
              const alts = await api.get(`/loans/${loan.id}/alternatives?end=${encodeURIComponent(end)}`);
              root.querySelector("#ext-alternatives").innerHTML = alts.length
                ? `<div class="alert-block warning"><strong>Outils équivalents libres sur ce créneau</strong><div class="card-sub">${alts
                    .map((a) => `${escapeHtml(a.name)} (${escapeHtml(a.code)})`)
                    .join(" · ")}</div></div>`
                : `<div class="card-sub">Aucun outil équivalent n'est libre sur ce créneau.</div>`;
            } catch {
              // les alternatives sont facultatives
            }
          }
        });
      },
    }
  );
}

function openModifyForm(loan, onDone) {
  openModal(
    `
    <div class="modal-header"><div class="card-title">Modifier la réservation</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    <form id="mod-form" class="form-grid">
      <div class="field"><label>Début</label><input type="datetime-local" name="start" value="${toDatetimeLocal(loan.start_datetime)}" required/></div>
      <div class="field"><label>Fin</label><input type="datetime-local" name="end" value="${toDatetimeLocal(loan.end_datetime_planned)}" required/></div>
      <div class="field"><label>Chantier</label><input name="site" value="${escapeHtml(loan.site || "")}"/></div>
      <div class="field"><label>Commentaire</label><textarea name="comment" rows="2">${escapeHtml(loan.comment || "")}</textarea></div>
      <button type="submit" class="btn btn-primary">Enregistrer</button>
    </form>`,
    {
      onMount: (root) => {
        root.querySelector("#c").addEventListener("click", closeModal);
        root.querySelector("#mod-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          const f = new FormData(e.target);
          try {
            await api.patch(`/loans/${loan.id}`, {
              start_datetime: new Date(f.get("start")).toISOString(),
              end_datetime_planned: new Date(f.get("end")).toISOString(),
              site: f.get("site") || null,
              comment: f.get("comment") || null,
            });
            toast("Réservation modifiée", "success");
            closeModal();
            onDone();
          } catch (err) {
            fail(err);
          }
        });
      },
    }
  );
}

function decisionForm(loan, approve, onDone) {
  openModal(
    `
    <div class="modal-header"><div class="card-title">${approve ? "Valider" : "Refuser"} la réservation</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    <form id="dec-form" class="form-grid">
      <div class="field"><label>Commentaire${approve ? " (optionnel)" : ""}</label><textarea name="comment" rows="2"></textarea></div>
      <button type="submit" class="btn ${approve ? "btn-primary" : "btn-danger"}">${approve ? "Valider" : "Refuser"}</button>
    </form>`,
    {
      onMount: (root) => {
        root.querySelector("#c").addEventListener("click", closeModal);
        root.querySelector("#dec-form").addEventListener("submit", async (e) => {
          e.preventDefault();
          try {
            await api.post(`/loans/${loan.id}/${approve ? "approve" : "reject"}`, { comment: new FormData(e.target).get("comment") || null });
            toast(approve ? "Réservation validée" : "Réservation refusée", "success");
            closeModal();
            onDone();
          } catch (err) {
            fail(err);
          }
        });
      },
    }
  );
}

async function openEvents(loan) {
  const events = await api.get(`/loans/${loan.id}/events`);
  openModal(
    `<div class="modal-header"><div class="card-title">Historique de la réservation</div><button class="btn btn-ghost btn-sm" id="c">Fermer</button></div>
    ${events
      .map(
        (e) => `<div class="card"><div class="card-row"><div class="card-title">${escapeHtml(EVENT_LABELS[e.kind] || e.kind)}</div>
        <div class="card-sub">${escapeHtml(formatDateTime(e.created_at))}</div></div>
        <div class="card-sub">${escapeHtml(e.user_name || "Automatique")}</div></div>`
      )
      .join("")}`,
    { onMount: (root) => root.querySelector("#c").addEventListener("click", closeModal) }
  );
}

export function openLoanDetailModal(loan, tool, onDone) {
  const mine = loan.borrower_id === state.user.id;
  const canAct = isManager() || mine || loan.created_by_id === state.user.id;
  const canDecide = isManager() && !mine;
  const status = loan.status;

  const buttons = [];
  if (canDecide && status === "attente_validation") {
    buttons.push('<button class="btn btn-sm btn-primary" id="d-approve">Valider</button>', '<button class="btn btn-sm btn-danger" id="d-reject">Refuser</button>');
  }
  if (canAct && status === "reserve") buttons.push('<button class="btn btn-sm btn-primary" id="d-checkout">Retirer l\'outil</button>', '<button class="btn btn-sm" id="d-modify">Modifier</button>');
  if (canAct && status === "attente_validation") buttons.push('<button class="btn btn-sm" id="d-modify">Modifier</button>');
  if (canAct && status === "en_cours") buttons.push('<button class="btn btn-sm btn-primary" id="d-return">Retour</button>', '<button class="btn btn-sm" id="d-extend">Prolonger</button>');
  if (canAct && ["reserve", "en_cours", "attente_validation"].includes(status)) buttons.push('<button class="btn btn-sm btn-danger" id="d-cancel">Annuler</button>');
  if (canAct && loan.series_id && ["reserve", "attente_validation"].includes(status)) buttons.push('<button class="btn btn-sm btn-danger" id="d-cancel-series">Annuler toute la série</button>');
  if (isManager() && !mine && status === "en_cours" && new Date(loan.end_datetime_planned) < new Date()) buttons.push('<button class="btn btn-sm" id="d-remind">Relancer</button>');

  openModal(
    `
    <div class="modal-header">
      <div class="card-title">${escapeHtml(tool?.name || "Outil")}</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <div class="card-meta" style="margin-bottom:0.5rem;">
      <span>Emprunteur : ${escapeHtml(getUserName(loan.borrower_id))}</span>
      <span>Chantier : ${escapeHtml(loan.site || "-")}</span>
      ${loanStatusBadge(status)}
      ${loan.series_id ? '<span class="badge badge-gray">Série</span>' : ""}
      ${loan.has_signature ? '<span class="badge badge-green">Signé</span>' : ""}
    </div>
    <div class="card-sub">${formatDateTime(loan.start_datetime)} → ${formatDateTime(loan.end_datetime_planned)}</div>
    ${loan.comment ? `<div class="card-sub">${escapeHtml(loan.comment)}</div>` : ""}
    ${loan.approval_comment ? `<div class="card-sub">Décision : ${escapeHtml(loan.approval_comment)}</div>` : ""}
    ${status === "termine" ? `<div class="card-sub">État : ${loan.state_before ?? "-"}/5 → ${loan.state_after ?? "-"}/5</div>` : ""}
    <div class="card-actions">${buttons.join("")}</div>
    <h4>Documents et agenda</h4>
    <div class="card-actions">
      <button class="btn btn-sm" id="d-voucher">Bon de sortie (PDF)</button>
      ${canAct ? '<button class="btn btn-sm" id="d-sign">Signature</button><button class="btn btn-sm" id="d-email">Envoyer par email</button>' : ""}
      <button class="btn btn-sm" id="d-ics">Ajouter à l'agenda</button>
      <button class="btn btn-sm" id="d-events">Historique</button>
      <button class="btn btn-sm" id="d-history">État de l'outil</button>
    </div>`,
    {
      onMount: (root) => {
        const on = (id, fn) => root.querySelector(id)?.addEventListener("click", fn);
        const done = () => {
          closeModal();
          onDone();
        };
        on("#form-close", closeModal);
        on("#d-return", () => openReturnForm(loan, onDone));
        on("#d-extend", () => openExtendForm(loan, onDone));
        on("#d-modify", () => openModifyForm(loan, onDone));
        on("#d-approve", () => decisionForm(loan, true, onDone));
        on("#d-reject", () => decisionForm(loan, false, onDone));
        on("#d-checkout", async () => {
          try {
            await api.post(`/loans/${loan.id}/checkout`, {});
            toast("Outil retiré", "success");
            done();
          } catch (err) {
            fail(err);
          }
        });
        on("#d-cancel", async () => {
          if (!(await confirmDialog("Annuler cette réservation ?", { danger: true }))) return;
          try {
            await api.delete(`/loans/${loan.id}`);
            toast("Réservation annulée", "success");
            done();
          } catch (err) {
            fail(err);
          }
        });
        on("#d-cancel-series", async () => {
          if (!(await confirmDialog("Annuler toutes les occurrences à venir de cette série ?", { danger: true }))) return;
          try {
            const res = await api.delete(`/loans/series/${loan.series_id}`);
            toast(`${res.cancelled} occurrence(s) annulée(s)`, "success");
            done();
          } catch (err) {
            fail(err);
          }
        });
        on("#d-remind", async () => {
          try {
            await api.post(`/loans/${loan.id}/remind`);
            toast("Rappel envoyé", "success");
          } catch (err) {
            fail(err);
          }
        });
        on("#d-voucher", () => api.download(`/loans/${loan.id}/voucher.pdf`, `bon-de-sortie-${loan.id}.pdf`).catch(fail));
        on("#d-ics", () => api.download(`/loans/${loan.id}/ics`, `reservation-${loan.id}.ics`).catch(fail));
        on("#d-events", () => openEvents(loan));
        on("#d-history", () => openToolHistory("agency", loan.tool_id, tool?.name || ""));
        on("#d-sign", () =>
          openSignaturePad(
            "Signature de l'emprunteur",
            async (signature, name) => {
              try {
                await api.post(`/loans/${loan.id}/signature`, { signature, signed_name: name });
                toast("Signature enregistrée", "success");
                onDone();
              } catch (err) {
                fail(err);
              }
            },
            getUserName(loan.borrower_id)
          )
        );
        on("#d-email", async () => {
          const to = await promptDialog("Adresse email du destinataire du bon de sortie", { placeholder: "nom@exemple.fr" });
          if (!to) return;
          api
            .post(`/loans/${loan.id}/voucher/email`, { to })
            .then((r) => toast(r.sent ? "Bon de sortie envoyé" : `Envoi impossible : ${r.detail}`, r.sent ? "success" : "error"))
            .catch(fail);
        });
      },
    }
  );
}
