import { api, ApiError } from "./api.js";
import { escapeHtml, openModal, closeModal } from "./ui.js";

const DEBOUNCE_MS = 250;
let timer = null;

function renderResults(container, data) {
  if (!data.categories.length) {
    container.innerHTML = `<div class="empty-state">Aucun résultat pour « ${escapeHtml(data.query)} ».</div>`;
    return;
  }
  container.innerHTML = data.categories
    .map(
      (cat) => `<div class="search-group">
        <div class="search-group-label">${escapeHtml(cat.label)}</div>
        ${cat.items.map((it) => `<a class="search-result" href="${it.link}">
          <span class="search-result-title">${escapeHtml(it.title)}</span>
          ${it.subtitle ? `<span class="search-result-sub">${escapeHtml(it.subtitle)}</span>` : ""}
        </a>`).join("")}
      </div>`
    )
    .join("");
  container.querySelectorAll(".search-result").forEach((a) => a.addEventListener("click", () => closeModal()));
}

export function openGlobalSearch() {
  openModal(
    `<div class="modal-header"><div class="card-title">Rechercher</div><button class="btn btn-ghost btn-sm" id="gs-close">Fermer</button></div>
    <input type="search" id="gs-input" class="search-input" placeholder="Outil, EPI, chantier, ticket, collègue…" autocomplete="off"/>
    <div id="gs-results"><div class="card-sub">Tapez au moins deux caractères.</div></div>`,
    {
      onMount: (root) => {
        const input = root.querySelector("#gs-input");
        const results = root.querySelector("#gs-results");
        input.focus();
        root.querySelector("#gs-close").addEventListener("click", closeModal);
        input.addEventListener("input", () => {
          clearTimeout(timer);
          const q = input.value.trim();
          if (q.length < 2) {
            results.innerHTML = `<div class="card-sub">Tapez au moins deux caractères.</div>`;
            return;
          }
          timer = setTimeout(async () => {
            try {
              const data = await api.get(`/search?q=${encodeURIComponent(q)}`);
              if (input.value.trim() === q) renderResults(results, data);
            } catch (err) {
              results.innerHTML = `<div class="empty-state">${escapeHtml(err instanceof ApiError ? err.message : "Erreur")}</div>`;
            }
          }, DEBOUNCE_MS);
        });
      },
    }
  );
}

export function initGlobalSearchShortcut() {
  document.addEventListener("keydown", (e) => {
    if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
    const tag = (document.activeElement && document.activeElement.tagName) || "";
    if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || document.activeElement?.isContentEditable) return;
    e.preventDefault();
    openGlobalSearch();
  });
}
