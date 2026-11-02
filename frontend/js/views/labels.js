import { api, ApiError } from "../api.js";
import { escapeHtml, toast } from "../ui.js";
import { barcodeSVG } from "../barcode.js";
import { qrSVG } from "../qr.js";

const TEMPLATES = {
  a4: "Planche A4 (grandes étiquettes)",
  adhesive: "Adhésives 63,5 × 38,1 mm (21 par page)",
  roll: "Rouleau 50 × 25 mm (une par étiquette)",
};
const SYMBOLS = { qr: "QR code", code39: "Code-barres", both: "QR + code-barres" };

const opts = { kind: "agency", template: "adhesive", symbol: "both", type: "", onlyUnprinted: false, q: "" };

function labelHtml(t) {
  const qr = opts.symbol !== "code39" ? `<div class="label-qr">${qrSVG(t.unique_code, { size: 72 })}</div>` : "";
  const bar = opts.symbol !== "qr" ? `<div class="label-bar">${barcodeSVG(t.unique_code, { moduleWidth: 1.2, height: 26 })}</div>` : "";
  return `<div class="label-card tpl-${opts.template}">
    <div class="label-name">${escapeHtml(t.name)}</div>
    <div class="label-body">${qr}${bar}</div>
    <div class="label-code">${escapeHtml(t.unique_code)}</div></div>`;
}

export async function renderLabels(app) {
  const params = new URLSearchParams({ kind: opts.kind });
  if (opts.type) params.set("type_", opts.type);
  if (opts.onlyUnprinted) params.set("only_unprinted", "true");
  if (opts.q) params.set("q", opts.q);
  let tools = [];
  try {
    tools = await api.get(`/tools/labels?${params}`);
  } catch (err) {
    toast(err instanceof ApiError ? err.message : "Erreur", "error");
  }
  const types = [...new Set(tools.map((t) => t.type).filter(Boolean))].sort();
  const sel = (map, current) => Object.entries(map).map(([k, v]) => `<option value="${k}" ${k === current ? "selected" : ""}>${v}</option>`).join("");

  app.innerHTML = `
    <div class="section-header no-print"><h1>Étiquettes</h1>
      <button class="btn btn-primary btn-sm" id="print-btn" ${tools.length ? "" : "disabled"}>Imprimer ${tools.length} étiquette(s)</button></div>
    <div class="filter-bar no-print">
      <select id="l-kind"><option value="agency" ${opts.kind === "agency" ? "selected" : ""}>Outils d'agence</option><option value="epi" ${opts.kind === "epi" ? "selected" : ""}>EPI</option></select>
      <select id="l-tpl">${sel(TEMPLATES, opts.template)}</select>
      <select id="l-sym">${sel(SYMBOLS, opts.symbol)}</select>
      <select id="l-type"><option value="">Tous les types</option>${types.map((t) => `<option ${t === opts.type ? "selected" : ""}>${escapeHtml(t)}</option>`).join("")}</select>
      <input id="l-q" placeholder="Rechercher" value="${escapeHtml(opts.q)}"/>
      <label><input type="checkbox" id="l-unprinted" ${opts.onlyUnprinted ? "checked" : ""}/> Non imprimées seulement</label>
    </div>
    <div class="labels-grid tpl-grid-${opts.template}" id="labels-sheet">${tools.map(labelHtml).join("") || '<div class="empty-state">Aucun outil.</div>'}</div>`;

  const bind = (id, key, ev = "change", get = (e) => e.target.value) =>
    document.getElementById(id).addEventListener(ev, (e) => {
      opts[key] = get(e);
      renderLabels(app);
    });
  bind("l-kind", "kind");
  bind("l-tpl", "template");
  bind("l-sym", "symbol");
  bind("l-type", "type");
  bind("l-unprinted", "onlyUnprinted", "change", (e) => e.target.checked);
  document.getElementById("l-q").addEventListener("change", (e) => {
    opts.q = e.target.value;
    renderLabels(app);
  });

  document.getElementById("print-btn").addEventListener("click", async () => {
    document.body.dataset.labelTpl = opts.template;
    window.print();
    try {
      await api.post("/tools/labels/printed", { kind: opts.kind, ids: tools.map((t) => t.id) });
    } catch {
      // le marquage est un confort : l'impression a déjà eu lieu
    }
  });
}
