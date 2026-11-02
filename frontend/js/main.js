import { registerRoute, startRouter, navigate } from "./router.js";
import { initTheme } from "./theme.js";
import { openGlobalSearch, initGlobalSearchShortcut } from "./globalSearch.js";
import { state, isLoggedIn, isAdmin, isManager, clearSession } from "./state.js";
import { api } from "./api.js";
import { wireImageFallbacks } from "./ui.js";
import { startNotificationPolling, stopNotificationPolling } from "./notifications.js";
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

const NAV_ITEMS = [
  { path: "/", label: "Accueil", icon: "home" },
  { path: "/mes-outils", label: "Mes outils", icon: "grid" },
  { path: "/agence", label: "Agence", icon: "building" },
  { path: "/reservations", label: "Réservations", icon: "calendar" },
  { path: "/transferts", label: "Prêts externes", icon: "exchange" },
  { path: "/entre-collegues", label: "Collègues", icon: "userCheck" },
  { path: "/inventaire", label: "Inventaire", icon: "clipboard" },
  { path: "/epi", label: "EPI", icon: "shield" },
  { path: "/controles", label: "Contrôles", icon: "check" },
  { path: "/notifications", label: "Alertes", icon: "bell", badge: true },
  { path: "/chantiers", label: "Chantiers", icon: "building" },
  { path: "/maintenance", label: "Maintenance", icon: "tool", managerOnly: true },
  { path: "/planification", label: "Planification", icon: "calendar", managerOnly: true },
  { path: "/utilisateurs", label: "Équipe", icon: "users", managerOnly: true },
  { path: "/utilisation", label: "Utilisation", icon: "chart", managerOnly: true },
  { path: "/finances", label: "Finances", icon: "chart", managerOnly: true },
];

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

function navLinks() {
  return NAV_ITEMS.filter((item) => !item.managerOnly || isManager())
    .map(
      (item) => `
        <a href="#${item.path}" class="nav-link" data-path="${item.path}">
          ${icon(item.icon, { size: 20 })}
          <span>${item.label}</span>
          ${item.badge ? '<span class="bell-badge hidden" data-bell-badge></span>' : ""}
        </a>`
    )
    .join("");
}

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

  header.innerHTML = `
    <div class="header-inner">
      <div class="header-brand">
        <div class="logo-box"><img src="/icons/fauche-logo-full.png" alt="Fauché" data-fallback-hide/></div>
        <span>Gestion Outillage</span>
      </div>
      <nav class="header-nav">${navLinks()}</nav>
      <div class="header-user">
        <button class="btn btn-ghost btn-sm" id="search-global" aria-label="Rechercher (touche /)">${icon("search", { size: 16 })} Rechercher</button>
        <button class="btn btn-ghost btn-sm" id="scan-global" aria-label="Scanner un outil">${icon("camera", { size: 16 })} Scanner</button>
        <a href="#/synchronisation" class="sync-pill hidden" id="sync-pill" data-sync-pill></a>
        <a href="#/mon-profil" class="user-name user-link">${state.user ? state.user.full_name : ""}</a>
        ${isAdmin() ? '<a href="#/parametres" class="btn btn-ghost btn-sm">Paramètres</a>' : ""}
        <button class="btn btn-ghost btn-sm" id="logout-btn">${icon("logout", { size: 16 })} Déconnexion</button>
      </div>
    </div>
  `;

  mobileNav.innerHTML = navLinks();
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

  const currentHash = location.hash.slice(1) || "/";
  document.querySelectorAll(".nav-link").forEach((link) => {
    if (link.dataset.path === currentHash) {
      link.classList.add("active");
    }
  });
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
initGlobalSearchShortcut();

window.addEventListener("hashchange", buildChrome);
buildChrome();
startRouter();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/service-worker.js").catch(() => {});
}
