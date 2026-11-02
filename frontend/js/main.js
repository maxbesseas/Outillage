import { registerRoute, startRouter, navigate } from "./router.js";
import { initTheme } from "./theme.js";
import { startWebcamPhotos } from "./cameraCapture.js";
import { openGlobalSearch, initGlobalSearchShortcut } from "./globalSearch.js";
import { state, isLoggedIn, isAdmin, isManager, clearSession } from "./state.js";
import { api } from "./api.js";
import { wireImageFallbacks, escapeHtml, startAccessibleForms } from "./ui.js";
import { startNotificationPolling, stopNotificationPolling, refreshNotificationCount } from "./notifications.js";
import { icon } from "./icons.js";
import { initAssistant, destroyAssistant } from "./assistant.js";

import { renderLogin } from "./views/login.js";
import { renderDashboard } from "./views/dashboard.js";
import { renderPersonalTools } from "./views/personalTools.js";
import { renderAgencyTools } from "./views/agencyTools.js";
import { renderLoans } from "./views/loans.js";
import { renderTransfers } from "./views/transfers.js";
import { renderPeerTransfers } from "./views/peerTransfers.js";
import { renderUsers } from "./views/users.js";
import { renderFinancial } from "./views/financial.js";
import { renderInventory } from "./views/inventory.js";
import { renderEpi } from "./views/epi.js";
import { renderLabels } from "./views/labels.js";
import { renderWarranty } from "./views/warranty.js";
import { renderSettings } from "./views/settings.js";
import { renderProfile } from "./views/profile.js";
import { renderForgotPassword } from "./views/forgotPassword.js";
import { renderResetPassword } from "./views/resetPassword.js";
import { renderAudit } from "./views/audit.js";
import { renderJobs } from "./views/jobs.js";
import { renderNotifications } from "./views/notifications.js";
import { renderControls } from "./views/controls.js";
import { renderPolicies } from "./views/policies.js";
import { renderCalibrations } from "./views/calibrations.js";
import { renderQualifications } from "./views/qualifications.js";
import { renderPlanning } from "./views/planning.js";
import { renderMaintenance } from "./views/maintenance.js";
import { renderStock } from "./views/stock.js";
import { renderSites } from "./views/sites.js";
import { renderUsage } from "./views/usage.js";
import { renderImports } from "./views/imports.js";
import { renderBackups } from "./views/backups.js";
import { renderAssistantInsights } from "./views/assistantInsights.js";
import { renderAssets, renderLosses, renderBudgets, renderExports } from "./views/financeAdvanced.js";
import { renderToolSheet, renderCodeRedirect } from "./views/toolSheet.js";
import { renderScan, renderSync, scanAndOpen } from "./views/scan.js";
import { startOfflineSync, onQueueChange } from "./offlineQueue.js";

const PRIMARY_NAV = [
  { path: "/", label: "Accueil", icon: "home" },
  { path: "/agence", label: "Agence", icon: "building" },
  { path: "/reservations", label: "Réservations", icon: "calendar" },
  { path: "/inventaire", label: "Inventaire", icon: "clipboard" },
  { path: "/controles", label: "Contrôles", icon: "check" },
];

const MORE_NAV = [
  {
    title: "Outillage",
    items: [
      { path: "/mes-outils", label: "Mes outils", icon: "grid" },
      { path: "/epi", label: "EPI", icon: "shield" },
      { path: "/transferts", label: "Prêts externes", icon: "exchange" },
      { path: "/entre-collegues", label: "Collègues", icon: "userCheck" },
      { path: "/chantiers", label: "Chantiers", icon: "building" },
    ],
  },
  {
    title: "Suivi",
    items: [
      { path: "/maintenance", label: "Maintenance", icon: "tool", managerOnly: true },
      { path: "/planification", label: "Planification", icon: "calendar", managerOnly: true },
      { path: "/utilisation", label: "Utilisation", icon: "chart", managerOnly: true },
      { path: "/finances", label: "Finances", icon: "chart", managerOnly: true },
      { path: "/utilisateurs", label: "Équipe", icon: "users", managerOnly: true },
    ],
  },
];

// Sur téléphone, l'inventaire rejoint le menu « Plus » pour garder des cibles larges.
const PHONE_NAV = PRIMARY_NAV.filter((item) => item.path !== "/inventaire");

function isCurrent(path, current) {
  return path === current || (path !== "/" && current.startsWith(`${path}/`));
}

function moreGroups(extra = []) {
  const groups = MORE_NAV.map((group) => ({ ...group, items: group.items.filter((item) => !item.managerOnly || isManager()) }));
  groups[0].items = [...extra, ...groups[0].items];
  return groups.filter((group) => group.items.length);
}

function morePanel(id, groups) {
  return `
    <div id="${id}" class="menu-panel menu-panel-more hidden">
      ${groups
        .map(
          (group) => `
            <div class="menu-group">
              <p class="menu-group-title">${group.title}</p>
              ${group.items
                .map((item) => `<a href="#${item.path}" class="menu-item nav-link" data-path="${item.path}">${icon(item.icon, { size: 20 })}<span>${item.label}</span></a>`)
                .join("")}
            </div>`
        )
        .join("")}
    </div>`;
}

function desktopNav(current) {
  const groups = moreGroups();
  const moreActive = groups.some((group) => group.items.some((item) => isCurrent(item.path, current)));
  return `
    ${PRIMARY_NAV.map((item) => `<a href="#${item.path}" class="nav-link" data-path="${item.path}">${item.label}</a>`).join("")}
    <div class="menu-anchor">
      <button type="button" class="nav-link nav-more${moreActive ? " active" : ""}" data-menu-toggle="menu-more" aria-haspopup="true" aria-expanded="false" aria-controls="menu-more">
        <span>Plus</span>${icon("chevronDown", { size: 16 })}
      </button>
      ${morePanel("menu-more", groups)}
    </div>`;
}

function phoneNav(current) {
  const inventory = PRIMARY_NAV.filter((item) => item.path === "/inventaire");
  const groups = moreGroups(inventory);
  const moreActive = groups.some((group) => group.items.some((item) => isCurrent(item.path, current)));
  return `
    ${PHONE_NAV.map((item) => `<a href="#${item.path}" class="nav-link" data-path="${item.path}">${icon(item.icon, { size: 22 })}<span>${item.label}</span></a>`).join("")}
    <button type="button" class="nav-link nav-more${moreActive ? " active" : ""}" data-menu-toggle="menu-more-phone" aria-haspopup="true" aria-expanded="false" aria-controls="menu-more-phone">
      ${icon("menu", { size: 22 })}<span>Plus</span>
    </button>
    ${morePanel("menu-more-phone", groups)}`;
}

function initials(name) {
  const letters = String(name || "").trim().split(/\s+/).slice(0, 2).map((part) => part[0] || "").join("");
  return escapeHtml(letters.toUpperCase() || "?");
}

function closeMenus(except = null) {
  document.querySelectorAll("[data-menu-toggle]").forEach((toggle) => {
    if (toggle === except) return;
    toggle.setAttribute("aria-expanded", "false");
    document.getElementById(toggle.dataset.menuToggle)?.classList.add("hidden");
  });
}

function wireMenus() {
  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-menu-toggle]");
    closeMenus(toggle);
    if (!toggle) return;
    const panel = document.getElementById(toggle.dataset.menuToggle);
    const opening = panel.classList.contains("hidden");
    panel.classList.toggle("hidden", !opening);
    toggle.setAttribute("aria-expanded", String(opening));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Escape") return;
    const open = document.querySelector('[data-menu-toggle][aria-expanded="true"]');
    if (!open) return;
    closeMenus();
    open.focus();
  });
}

registerRoute("/login", renderLogin);
registerRoute("/mot-de-passe-oublie", renderForgotPassword);
registerRoute("/reinitialiser", renderResetPassword);
registerRoute("/mon-profil", renderProfile);
registerRoute("/", renderDashboard);
registerRoute("/mes-outils", renderPersonalTools);
registerRoute("/salaries/:id", renderPersonalTools, { guard: isManager });
registerRoute("/agence", renderAgencyTools);
registerRoute("/reservations", renderLoans);
registerRoute("/transferts", renderTransfers);
registerRoute("/entre-collegues", renderPeerTransfers);
registerRoute("/utilisateurs", renderUsers, { guard: isManager });
registerRoute("/finances", renderFinancial, { guard: isManager });
registerRoute("/finances/actifs", renderAssets, { guard: isManager });
registerRoute("/finances/pertes", renderLosses, { guard: isManager });
registerRoute("/finances/budgets", renderBudgets, { guard: isManager });
registerRoute("/exports", renderExports, { guard: isManager });
registerRoute("/inventaire", renderInventory);
registerRoute("/epi", renderEpi);
registerRoute("/etiquettes", renderLabels, { guard: isManager });
registerRoute("/garanties", renderWarranty, { guard: isManager });
registerRoute("/parametres", renderSettings, { guard: isAdmin });
registerRoute("/audit", renderAudit, { guard: isAdmin });
registerRoute("/taches", renderJobs, { guard: isAdmin });
registerRoute("/notifications", renderNotifications);
registerRoute("/controles", renderControls);
registerRoute("/periodicites", renderPolicies, { guard: isAdmin });
registerRoute("/etalonnages", renderCalibrations);
registerRoute("/habilitations", renderQualifications);
registerRoute("/planification", renderPlanning);
registerRoute("/maintenance", renderMaintenance);
registerRoute("/chantiers", renderSites);
registerRoute("/utilisation", renderUsage, { guard: isManager });
registerRoute("/import", renderImports, { guard: isManager });
registerRoute("/sauvegardes", renderBackups, { guard: isAdmin });
registerRoute("/assistant-suivi", renderAssistantInsights, { guard: isAdmin });
registerRoute("/stock", renderStock, { guard: isManager });
registerRoute("/outil/:kind/:id", renderToolSheet);
registerRoute("/code/:code", renderCodeRedirect);
registerRoute("/scan", renderScan);
registerRoute("/synchronisation", renderSync);

function buildChrome() {
  const header = document.getElementById("app-header");
  const mobileNav = document.getElementById("mobile-nav");

  if (!isLoggedIn()) {
    header.classList.add("hidden");
    mobileNav.classList.add("hidden");
    destroyAssistant();
    stopNotificationPolling();
    return;
  }

  header.classList.remove("hidden");
  mobileNav.classList.remove("hidden");
  initAssistant();
  startNotificationPolling();
  startOfflineSync();

  const current = (location.hash.slice(1) || "/").split("?")[0];
  const fullName = state.user ? state.user.full_name : "";
  header.innerHTML = `
    <div class="header-inner">
      <a href="#/" class="header-brand" aria-label="Fauché, accueil">
        <span class="logo-box"><img src="/icons/fauche-logo-full.png" alt="" data-fallback-hide/></span>
        <span class="header-title">Gestion Outillage</span>
      </a>
      <nav class="header-nav" aria-label="Navigation principale">${desktopNav(current)}</nav>
      <div class="header-user">
        <a href="#/synchronisation" class="sync-pill hidden" id="sync-pill" data-sync-pill></a>
        <button type="button" class="header-search" id="search-global" aria-label="Rechercher (touche /)">
          ${icon("search", { size: 18 })}<span class="header-label">Rechercher</span><kbd class="header-label">/</kbd>
        </button>
        <button type="button" class="header-icon" id="scan-global" aria-label="Scanner un outil" title="Scanner un outil">${icon("camera", { size: 20 })}</button>
        <a href="#/notifications" class="header-icon nav-link" data-path="/notifications" aria-label="Alertes" title="Alertes">
          ${icon("bell", { size: 20 })}<span class="bell-badge hidden" data-bell-badge></span>
        </a>
        <div class="menu-anchor">
          <button type="button" class="header-account" data-menu-toggle="menu-account" aria-haspopup="true" aria-expanded="false" aria-controls="menu-account" aria-label="Mon compte">
            <span class="header-avatar" aria-hidden="true">${initials(fullName)}</span>
            <span class="header-label header-account-name">${escapeHtml(fullName)}</span>
            <span class="header-label">${icon("chevronDown", { size: 16 })}</span>
          </button>
          <div id="menu-account" class="menu-panel menu-panel-account hidden">
            <p class="menu-account-name">${escapeHtml(fullName)}</p>
            <a href="#/mon-profil" class="menu-item nav-link" data-path="/mon-profil">${icon("userCheck", { size: 20 })}<span>Mon profil</span></a>
            ${isAdmin() ? `<a href="#/parametres" class="menu-item nav-link" data-path="/parametres">${icon("wrench", { size: 20 })}<span>Paramètres</span></a>` : ""}
            <button type="button" class="menu-item menu-item-logout" id="logout-btn">${icon("logout", { size: 20 })}<span>Déconnexion</span></button>
          </div>
        </div>
      </div>
    </div>
  `;

  mobileNav.innerHTML = phoneNav(current);
  wireImageFallbacks(header);

  document.getElementById("search-global").addEventListener("click", openGlobalSearch);
  document.getElementById("scan-global").addEventListener("click", scanAndOpen);
  refreshSyncPill();

  const logoutBtn = document.getElementById("logout-btn");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      const refreshToken = state.refreshToken;
      if (refreshToken) {
        try {
          await api.post("/auth/logout", { refresh_token: refreshToken });
        } catch {
          // la déconnexion locale reste effective même si le serveur est injoignable
        }
      }
      clearSession();
      navigate("/login");
      buildChrome();
    });
  }

  document.querySelectorAll(".nav-link[data-path]").forEach((link) => {
    if (isCurrent(link.dataset.path, current)) {
      link.classList.add("active");
      link.setAttribute("aria-current", "page");
    }
  });
  if (isLoggedIn()) refreshNotificationCount();
}

let pendingActions = 0;

function refreshSyncPill() {
  const pill = document.getElementById("sync-pill");
  if (!pill) return;
  const offline = !navigator.onLine;
  pill.classList.toggle("hidden", !offline && pendingActions === 0);
  pill.classList.toggle("offline", offline);
  pill.textContent = offline ? `Hors ligne${pendingActions ? ` · ${pendingActions} en attente` : ""}` : `${pendingActions} à synchroniser`;
}

onQueueChange((n) => {
  pendingActions = n;
  refreshSyncPill();
});
window.addEventListener("online", refreshSyncPill);
window.addEventListener("offline", refreshSyncPill);

initTheme();
startAccessibleForms();
startWebcamPhotos();
initGlobalSearchShortcut();
wireMenus();

window.addEventListener("hashchange", buildChrome);
buildChrome();
startRouter();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}
