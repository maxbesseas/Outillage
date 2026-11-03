import { api, ApiError, apiRequest } from "../api.js";
import { escapeHtml, formatDateTime, toast, openModal, closeModal } from "../ui.js";
import { isAdmin } from "../state.js";
import { getAgencies } from "../agencies.js";

const fail = (err) => toast(err instanceof ApiError ? err.message : "Erreur", "error");
const TARGET_LABEL = { agency_tools: "Outils d'agence", epi: "EPI", users: "Utilisateurs" };
const ACTION = { create: ["green", "Création"], update: ["blue", "Mise à jour"], skip: ["gray", "Ignorée"], error: ["red", "Erreur"] };

let wizard = null;

async function postFile(path, fields) {
  const form = new FormData();
  Object.entries(fields).forEach(([k, v]) => v !== undefined && v !== null && form.append(k, v));
  return apiRequest(path, { method: "POST", body: form });
}

export async function renderImports(app) {
  const [fields, reports, excelStatus] = await Promise.all([api.get("/imports/fields"), api.get("/imports"), api.get("/imports/from-excel/status")]);
  if (!wizard) wizard = { target: "agency_tools", file: null, preview: null, mapping: {}, update: false, skipErrors: false, agency: "" };
  const canUsers = !!fields.users;
  const agencies = isAdmin() ? await getAgencies() : [];

  const w = wizard;
  const mappingHtml = w.preview
    ? `<h3>2. Associer les colonnes</h3>
       <p class="card-sub">Fichier « ${escapeHtml(w.preview.filename)} » — ${w.preview.total_rows} ligne(s)${w.preview.sheets.length > 1 ? ` · feuille « ${escapeHtml(w.preview.sheet)} »` : ""}. Les colonnes reconnues sont déjà associées.</p>
       <div class="table-wrap"><table class="data-table"><thead><tr>${w.preview.headers.map((h) => `<th>${escapeHtml(h)}</th>`).join("")}</tr></thead>
         <tbody>${w.preview.sample.map((r) => `<tr>${r.map((c) => `<td>${escapeHtml(c)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
       <div class="form-grid">${fields[w.target].fields
         .map((f) => `<div class="field"><label>${escapeHtml(f.label)}${fields[w.target].required.includes(f.key) ? " *" : ""}</label>
           <select data-map="${f.key}"><option value="">— ne pas importer —</option>${w.preview.headers
             .map((h, i) => `<option value="${i}" ${w.mapping[f.key] === i ? "selected" : ""}>${escapeHtml(h || `(colonne ${i + 1})`)}</option>`)
             .join("")}</select></div>`)
         .join("")}</div>
       ${agencies.length && w.target !== "users" ? `<div class="field"><label>Agence de destination</label><select id="imp-agency"><option value="">— choisir —</option>${agencies.map((a) => `<option ${w.agency === a.name ? "selected" : ""}>${escapeHtml(a.name)}</option>`).join("")}</select></div>` : ""}
       ${w.target !== "users" ? `<label><input type="checkbox" id="imp-update" ${w.update ? "checked" : ""}/> Mettre à jour les codes déjà présents (sinon ils sont ignorés)</label><br/>` : ""}
       <label><input type="checkbox" id="imp-skip" ${w.skipErrors ? "checked" : ""}/> Ignorer les lignes en erreur (sinon rien n'est importé s'il y a une erreur)</label>
       <div class="card-actions"><button class="btn btn-primary" id="imp-sim">Simuler l'import</button></div>`
    : "";

  app.innerHTML = `
    <div class="section-header"><h1>Import de données</h1></div>
    <p class="card-sub">Importez un fichier Excel (.xlsx) ou CSV. Vous verrez d'abord une simulation ligne par ligne : rien n'est enregistré tant que vous ne validez pas.</p>
    <h3>1. Choisir le fichier</h3>
    <div class="filter-bar">
      <select id="imp-target" aria-label="Type de données à importer">${Object.entries(TARGET_LABEL).filter(([k]) => k !== "users" || canUsers).map(([k, v]) => `<option value="${k}" ${w.target === k ? "selected" : ""}>${v}</option>`).join("")}</select>
      <input type="file" id="imp-file" aria-label="Fichier à importer" accept=".xlsx,.csv,.txt"/>
      <a class="btn btn-sm" href="#" id="imp-template">Télécharger un modèle</a>
    </div>
    ${mappingHtml}
    <div id="imp-report"></div>
    ${excelStatus.enabled ? `<h3>Relire le classeur Excel de l'agence</h3>
    <p class="card-sub">Met à jour la base à partir du fichier « Inventaire matériel … » posé sur le serveur (nouveaux outils et modifications).</p>
    ${isAdmin() ? `<div class="field"><label for="imp-excel-agency">Agence à relire</label><select id="imp-excel-agency"><option value="">Choisir une agence</option>${agencies.map((a) => `<option value="${escapeHtml(a.name)}">${escapeHtml(a.name)}</option>`).join("")}</select></div>` : ""}
    <div class="card-actions"><button class="btn btn-sm" id="imp-excel-sim">Simuler</button><button class="btn btn-sm" id="imp-excel-commit">Relire et appliquer</button></div>` : ""}
    <h3>Historique</h3>
    ${reports.map((r) => `<div class="card"><div class="card-row"><div class="card-title">${escapeHtml(TARGET_LABEL[r.target] || r.target)} — ${escapeHtml(r.filename || "")}</div>
      <span class="badge badge-${r.mode === "commit" ? "green" : "gray"}">${r.mode === "commit" ? "Appliqué" : "Simulation"}</span></div>
      <div class="card-sub">${escapeHtml(formatDateTime(r.created_at))} · ${r.created} créé(s), ${r.updated} mis à jour, ${r.skipped} ignoré(s), ${r.errors} erreur(s)</div></div>`).join("") || '<div class="empty-state">Aucun import pour le moment.</div>'}`;

  document.getElementById("imp-target").addEventListener("change", (e) => {
    wizard = { ...w, target: e.target.value, preview: null, mapping: {} };
    renderImports(app);
  });
  document.getElementById("imp-template").addEventListener("click", async (e) => {
    e.preventDefault();
    try {
      await api.download(`/imports/template/${w.target}`, `modele-import-${w.target}.xlsx`);
    } catch (err) {
      fail(err);
    }
  });
  document.getElementById("imp-file").addEventListener("change", async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    try {
      const preview = await postFile("/imports/preview", { file });
      wizard = { ...w, file, preview, mapping: { ...preview.suggestions[w.target] } };
      renderImports(app);
    } catch (err) {
      fail(err);
    }
  });
  app.querySelectorAll("[data-map]").forEach((sel) =>
    sel.addEventListener("change", () => {
      w.mapping[sel.dataset.map] = sel.value === "" ? null : Number(sel.value);
    })
  );
  document.getElementById("imp-agency")?.addEventListener("change", (e) => (w.agency = e.target.value));
  document.getElementById("imp-update")?.addEventListener("change", (e) => (w.update = e.target.checked));
  document.getElementById("imp-skip")?.addEventListener("change", (e) => (w.skipErrors = e.target.checked));

  const run = async (mode) => {
    const mapping = Object.fromEntries(Object.entries(w.mapping).filter(([, v]) => v !== null && v !== undefined));
    try {
      const result = await postFile("/imports/run", {
        file: w.file, target: w.target, mapping: JSON.stringify(mapping), mode, update_existing: w.update, skip_errors: w.skipErrors,
        agency_number: w.agency || undefined,
      });
      showReport(app, result, mode);
    } catch (err) {
      fail(err);
    }
  };
  document.getElementById("imp-sim")?.addEventListener("click", () => run("simulate"));

  const excel = async (mode) => {
    try {
      const agency = document.getElementById("imp-excel-agency")?.value;
      if (isAdmin() && !agency) {
        toast("Choisissez l'agence à relire", "error");
        return;
      }
      const query = new URLSearchParams({ mode, ...(agency ? { agency_number: agency } : {}) });
      showReport(app, await api.post(`/imports/from-excel?${query}`), mode);
    } catch (err) {
      fail(err);
    }
  };
  document.getElementById("imp-excel-sim")?.addEventListener("click", () => excel("simulate"));
  document.getElementById("imp-excel-commit")?.addEventListener("click", () => excel("commit"));
}

function showReport(app, r, mode) {
  const box = document.getElementById("imp-report");
  const c = r.counts;
  box.innerHTML = `
    <h3>${mode === "commit" ? "Import appliqué" : "Résultat de la simulation"}</h3>
    <div class="stat-grid">
      <div class="stat-tile"><div class="stat-value">${c.create}</div><div class="stat-label">À créer</div></div>
      <div class="stat-tile"><div class="stat-value">${c.update}</div><div class="stat-label">À mettre à jour</div></div>
      <div class="stat-tile"><div class="stat-value">${c.skip}</div><div class="stat-label">Ignorées</div></div>
      <div class="stat-tile"><div class="stat-value ${c.error ? "neg" : ""}">${c.error}</div><div class="stat-label">En erreur</div></div>
    </div>
    <div class="table-wrap"><table class="data-table"><thead><tr><th>Ligne</th><th>Élément</th><th>Action</th><th>Détail</th></tr></thead><tbody>
      ${r.rows
        .filter((x) => x.action !== "skip" || x.warnings.length)
        .slice(0, 300)
        .map((x) => `<tr><td>${x.row}</td><td>${escapeHtml(x.label)}</td><td><span class="badge badge-${ACTION[x.action][0]}">${ACTION[x.action][1]}</span></td>
          <td>${escapeHtml([...x.errors, ...x.warnings].join(" ; "))}</td></tr>`)
        .join("") || '<tr><td colspan="4">Rien à signaler.</td></tr>'}
    </tbody></table></div>
    ${mode === "simulate" && wizard?.preview ? `<div class="card-actions"><button class="btn btn-primary" id="imp-commit" ${c.create + c.update === 0 ? "disabled" : ""}>Valider l'import (${c.create} création(s), ${c.update} mise(s) à jour)</button></div>` : ""}`;
  document.getElementById("imp-commit")?.addEventListener("click", async () => {
    const w = wizard;
    const mapping = Object.fromEntries(Object.entries(w.mapping).filter(([, v]) => v !== null && v !== undefined));
    try {
      const result = await postFile("/imports/run", {
        file: w.file, target: w.target, mapping: JSON.stringify(mapping), mode: "commit", update_existing: w.update, skip_errors: w.skipErrors,
        agency_number: w.agency || undefined,
      });
      wizard = null;
      if (result.credentials && result.credentials.length) showCredentials(result.credentials, () => renderImports(app));
      else {
        toast(`Import appliqué : ${result.counts.create} créé(s), ${result.counts.update} mis à jour`, "success");
        renderImports(app);
      }
    } catch (err) {
      fail(err);
    }
  });
}

function showCredentials(credentials, onClose) {
  openModal(
    `<div class="modal-header"><div class="card-title">Mots de passe temporaires</div></div>
    <p class="card-sub">Ils ne seront plus affichés. Transmettez-les aux intéressés : un nouveau mot de passe leur sera demandé à la première connexion.</p>
    <div class="table-wrap"><table class="data-table"><tbody>${credentials.map((c) => `<tr><td>${escapeHtml(c.username)}</td><td><code>${escapeHtml(c.temporary_password)}</code></td></tr>`).join("")}</tbody></table></div>
    <div class="card-actions"><button class="btn btn-primary" id="cred-done">J'ai noté les mots de passe</button></div>`,
    {
      onMount: (root) =>
        root.querySelector("#cred-done").addEventListener("click", () => {
          closeModal();
          onClose();
        }),
    }
  );
}
