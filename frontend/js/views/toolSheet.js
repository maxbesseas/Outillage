import { api, ApiError } from "../api.js";
import { escapeHtml, formatDate, formatDateTime, stateStars, agencyStatusBadge, toast, openModal, closeModal } from "../ui.js";
import { cachedGet } from "../offlineQueue.js";
import { compressImage } from "../images.js";
import { openReportProblem } from "../reportProblem.js";
import { openInspectionForm } from "../inspectionForm.js";
import { openReserveForm } from "../reservationForm.js";
import { openToolHistory } from "../toolHistory.js";
import { openAccessories, openExitForm } from "../toolExtras.js";
import { qrSVG } from "../qr.js";
import { isManager } from "../state.js";

const KIND_LABEL = { agency: "Outil d'agence", epi: "EPI", personal: "Outil personnel" };
const PHOTO_KIND = { reference: "Référence", etat: "État", dommage: "Dommage", autre: "Autre" };
const CONTROL = { ok: ["green", "Contrôle à jour"], soon: ["orange", "Contrôle bientôt dû"], overdue: ["red", "Contrôle en retard"], never: ["gray", "Jamais contrôlé"] };
const fail = (err) => toast(err instanceof ApiError ? err.message : "Erreur", "error");

export async function renderCodeRedirect(app, params) {
  app.innerHTML = `<div class="empty-state">Recherche de l'outil…</div>`;
  try {
    const tool = await api.get(`/tools/lookup?code=${encodeURIComponent(params.code)}`);
    location.replace(`#/outil/${tool.kind}/${tool.id}`);
  } catch (err) {
    app.innerHTML = `<div class="empty-state">${escapeHtml(err instanceof ApiError ? err.message : "Erreur")}</div>`;
  }
}

export async function renderToolSheet(app, params) {
  const { kind, id } = params;
  let result;
  try {
    result = await cachedGet(`/tools/${kind}/${id}/sheet`, api);
  } catch (err) {
    app.innerHTML = `<div class="empty-state">${escapeHtml(err instanceof ApiError ? err.message : "Erreur")}</div>`;
    return;
  }
  const t = result.data;
  const reload = () => renderToolSheet(app, params);
  const ctl = t.control ? CONTROL[t.control.status] : null;

  app.innerHTML = `
    <div class="section-header"><h1>${escapeHtml(t.name)}</h1><div class="section-links"><a href="#/agence">Retour</a></div></div>
    ${result.offline ? `<div class="notice">Mode hors ligne : fiche enregistrée le ${escapeHtml(formatDateTime(new Date(result.at).toISOString()))}. Les informations peuvent avoir changé.</div>` : ""}
    <div class="card">
      <div class="card-with-thumb">
        ${t.photo_path ? `<img class="thumb" src="${escapeHtml(t.photo_path)}" alt=""/>` : `<div class="thumb"></div>`}
        <div style="flex:1;">
          <div class="card-row"><div class="card-title">${escapeHtml([t.type, t.brand].filter(Boolean).join(" · ") || KIND_LABEL[t.kind])}</div>
            <div class="state-stars">${stateStars(t.state)}</div></div>
          <div class="card-meta">
            <span class="badge badge-gray">${escapeHtml(KIND_LABEL[t.kind])}</span>
            ${t.status ? agencyStatusBadge(t.status) : ""}
            <span>Code : ${escapeHtml(t.unique_code)}</span>
            ${t.agency_number ? `<span>Agence ${escapeHtml(t.agency_number)}</span>` : ""}
            ${t.holder_name ? `<span>Détenteur : ${escapeHtml(t.holder_name)}</span>` : ""}
            ${t.serial_number ? `<span>N° de série : ${escapeHtml(t.serial_number)}</span>` : ""}
          </div>
          ${ctl ? `<div class="card-meta"><span class="badge badge-${ctl[0]}"><span class="dot"></span>${ctl[1]}</span>${t.control.due ? `<span>Échéance : ${formatDate(t.control.due)}</span>` : ""}</div>` : ""}
          ${t.expiration_date ? `<div class="card-meta"><span>Péremption : ${formatDate(t.expiration_date)}</span></div>` : ""}
          ${t.warranty && t.warranty.expires ? `<div class="card-meta"><span class="badge badge-${t.warranty.active ? "green" : "gray"}">Garantie ${t.warranty.active ? "active" : "expirée"} · ${formatDate(t.warranty.expires)}</span></div>` : ""}
        </div>
        <div class="qr-box" title="QR code de l'outil">${qrSVG(t.unique_code, { size: 84 })}</div>
      </div>
      ${t.comment ? `<div class="card-sub">${escapeHtml(t.comment)}</div>` : ""}
    </div>

    <div class="action-grid" id="sheet-actions">
      ${t.kind === "agency" && t.status === "disponible" ? '<button class="btn btn-primary" data-a="reserve">Réserver</button>' : ""}
      <button class="btn" data-a="problem">Signaler un problème</button>
      ${t.kind !== "epi" || isManager() ? '<button class="btn" data-a="inspect">Contrôle détaillé</button>' : ""}
      <button class="btn" data-a="history">Historique</button>
      ${t.kind === "agency" ? '<button class="btn" data-a="accessories">Accessoires</button>' : ""}
      ${t.kind === "agency" && t.can_manage ? '<button class="btn btn-danger" data-a="exit">Sortie de parc</button>' : ""}
    </div>

    ${t.current_loan ? `<div class="card"><div class="card-title">Actuellement chez ${escapeHtml(t.current_loan.borrower_name || "-")}</div>
      <div class="card-sub">Retour prévu le ${escapeHtml(formatDateTime(t.current_loan.end_datetime_planned))}${t.current_loan.site ? ` · ${escapeHtml(t.current_loan.site)}` : ""}</div></div>` : ""}
    ${t.next_reservations && t.next_reservations.length ? `<h3>Prochaines réservations</h3>${t.next_reservations.map((r) => `<div class="card-sub">${escapeHtml(r.borrower_name || "-")} — ${escapeHtml(formatDateTime(r.start_datetime))} → ${escapeHtml(formatDateTime(r.end_datetime_planned))}</div>`).join("")}` : ""}
    ${t.accessories && t.accessories.length ? `<h3>Accessoires</h3>${t.accessories.map((a) => `<div class="card-sub">${escapeHtml(a.name)} × ${a.quantity}${a.required ? "" : " (facultatif)"}</div>`).join("")}` : ""}
    ${t.open_tickets.length ? `<h3>Tickets ouverts</h3>${t.open_tickets.map((k) => `<div class="card-sub"><span class="badge badge-orange">${escapeHtml(k.status)}</span> ${escapeHtml(k.category)} · ${escapeHtml(k.severity)} · ${formatDate(k.opened_at)}</div>`).join("")}` : ""}

    <h3>Photos</h3>
    <div class="photo-grid">
      ${t.photos.map((p) => `<figure class="photo-tile" data-photo="${p.id}"><a href="${escapeHtml(p.path)}" target="_blank" rel="noopener"><img src="${escapeHtml(p.path)}" alt="" loading="lazy"/></a>
        <figcaption>${escapeHtml(PHOTO_KIND[p.kind] || p.kind)} · ${formatDate(p.created_at)}${p.caption ? `<br/>${escapeHtml(p.caption)}` : ""}</figcaption></figure>`).join("") || '<div class="card-sub">Aucune photo.</div>'}
    </div>
    <form id="photo-form" class="filter-bar">
      <select name="kind">${Object.entries(PHOTO_KIND).map(([k, v]) => `<option value="${k}" ${k === "etat" ? "selected" : ""}>${v}</option>`).join("")}</select>
      <input name="caption" placeholder="Légende (facultatif)"/>
      <input type="file" name="file" accept="image/*" capture="environment" required/>
      <button class="btn btn-sm">Ajouter la photo</button>
    </form>`;

  const tool = { id: t.id, name: t.name };
  app.querySelectorAll("[data-a]").forEach((b) =>
    b.addEventListener("click", async () => {
      try {
        switch (b.dataset.a) {
          case "reserve":
            openReserveForm(await api.get(`/agency-tools/${t.id}`), reload);
            break;
          case "problem":
            openReportProblem(t.kind, tool, reload);
            break;
          case "inspect":
            openInspectionForm(t.kind, t.id, reload);
            break;
          case "history":
            openToolHistory(t.kind, t.id, t.name);
            break;
          case "accessories":
            openAccessories(tool);
            break;
          case "exit":
            openExitForm(tool, () => {
              location.hash = "#/agence";
            });
            break;
        }
      } catch (err) {
        fail(err);
      }
    })
  );

  document.getElementById("photo-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try {
      const file = await compressImage(f.get("file"));
      const q = `photo_kind=${f.get("kind")}${f.get("caption") ? `&caption=${encodeURIComponent(f.get("caption"))}` : ""}`;
      await api.upload(`/tool-photos/${t.kind}/${t.id}?${q}`, file);
      toast("Photo ajoutée", "success");
      reload();
    } catch (err) {
      fail(err instanceof TypeError ? new ApiError("Hors ligne : la photo n'a pas pu être envoyée") : err);
    }
  });

  app.querySelectorAll("[data-photo]").forEach((fig) =>
    fig.addEventListener("dblclick", () =>
      openModal(
        `<div class="modal-header"><div class="card-title">Supprimer cette photo ?</div></div>
        <div class="card-actions"><button class="btn btn-danger" id="yes">Supprimer</button><button class="btn" id="no">Annuler</button></div>`,
        {
          onMount: (root) => {
            root.querySelector("#no").addEventListener("click", closeModal);
            root.querySelector("#yes").addEventListener("click", async () => {
              try {
                await api.delete(`/tool-photos/${fig.dataset.photo}`);
                closeModal();
                reload();
              } catch (err) {
                fail(err);
              }
            });
          },
        }
      )
    )
  );
}
