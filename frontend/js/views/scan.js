import { api, ApiError } from "../api.js";
import { escapeHtml, formatDateTime, toast } from "../ui.js";
import { openScanner } from "../scanner.js";
import { icon } from "../icons.js";
import { listQueue, flushQueue, retryEntry, discardEntry } from "../offlineQueue.js";

const RESULT = { ok: ["green", "Trouvé"], not_found: ["red", "Inconnu"], forbidden: ["orange", "Autre agence"] };
let scanned = [];

export function scanAndOpen() {
  openScanner((code) => {
    location.hash = `#/code/${encodeURIComponent(code)}`;
  });
}

export async function renderScan(app) {
  let results = [];
  if (scanned.length) {
    try {
      results = await api.post("/tools/lookup-batch", { codes: scanned });
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Hors ligne : vérification impossible", "error");
    }
  }
  app.innerHTML = `
    <div class="section-header"><h1>Scan par lot</h1></div>
    <p class="card-sub">Scannez plusieurs outils à la suite pour les retrouver d'un coup (inventaire rapide, vérification d'un coffre de camion…).</p>
    <div class="card-actions">
      <button class="btn btn-primary" id="scan-next">${icon("camera", { size: 16 })} Scanner un code</button>
      <button class="btn" id="scan-clear" ${scanned.length ? "" : "disabled"}>Vider la liste</button>
    </div>
    <form id="manual" class="filter-bar"><input name="code" placeholder="Saisir un code" autocomplete="off"/><button class="btn btn-sm">Ajouter</button></form>
    ${results.length ? `<div class="card-sub">${results.filter((r) => r.result === "ok").length} outil(s) reconnu(s) sur ${results.length}</div>` : '<div class="empty-state">Aucun code scanné.</div>'}
    ${results
      .map((r) => {
        const [color, label] = RESULT[r.result];
        return `<div class="card"><div class="card-row"><div class="card-title">${r.tool ? `<a href="#/outil/${escapeHtml(r.tool.kind)}/${r.tool.id}">${escapeHtml(r.tool.name)}</a>` : escapeHtml(r.code)}</div>
          <span class="badge badge-${color}"><span class="dot"></span>${label}</span></div>
          <div class="card-sub">${escapeHtml(r.code)}${r.tool && r.tool.holder_name ? ` · ${escapeHtml(r.tool.holder_name)}` : ""}</div></div>`;
      })
      .join("")}`;

  const add = (code) => {
    if (code && !scanned.includes(code)) scanned.push(code);
    renderScan(app);
  };
  document.getElementById("scan-next").addEventListener("click", () => openScanner(add));
  document.getElementById("scan-clear").addEventListener("click", () => {
    scanned = [];
    renderScan(app);
  });
  document.getElementById("manual").addEventListener("submit", (e) => {
    e.preventDefault();
    add(new FormData(e.target).get("code").trim());
  });
}

export async function renderSync(app) {
  const items = await listQueue();
  app.innerHTML = `
    <div class="section-header"><h1>Synchronisation</h1><button class="btn btn-sm" id="sync-now">Synchroniser maintenant</button></div>
    <p class="card-sub">${navigator.onLine ? "Réseau disponible." : "Vous êtes hors ligne : les actions ci-dessous partiront au retour du réseau."}</p>
    ${items.length
      ? items.map((e) => `<div class="card" data-id="${e.id}">
        <div class="card-row"><div class="card-title">${escapeHtml(e.label || e.path)}</div>
          <span class="badge badge-${e.status === "conflict" ? "red" : "orange"}">${e.status === "conflict" ? "Refusée" : "En attente"}</span></div>
        <div class="card-sub">Saisie le ${escapeHtml(formatDateTime(e.created))}${e.error ? ` — ${escapeHtml(e.error)}` : ""}</div>
        <div class="card-actions">${e.status === "conflict" ? '<button class="btn btn-sm" data-act="retry">Réessayer</button>' : ""}<button class="btn btn-sm btn-danger" data-act="discard">Abandonner</button></div></div>`).join("")
      : '<div class="empty-state">Rien en attente : tout est synchronisé.</div>'}`;

  document.getElementById("sync-now").addEventListener("click", async () => {
    await flushQueue();
    renderSync(app);
  });
  app.querySelectorAll("[data-act]").forEach((b) =>
    b.addEventListener("click", async () => {
      const id = Number(b.closest(".card").dataset.id);
      if (b.dataset.act === "retry") await retryEntry(id);
      else await discardEntry(id);
      renderSync(app);
    })
  );
}
