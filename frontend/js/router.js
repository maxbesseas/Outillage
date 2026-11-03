import { isLoggedIn, mustChangePassword } from "./state.js";
import { closeModal } from "./ui.js";

const routes = [];

const PUBLIC_PATHS = ["/login", "/mot-de-passe-oublie", "/reinitialiser"];
const FORCED_PATH = "/mon-profil";

export function registerRoute(path, renderFn, options = {}) {
  const paramNames = [];
  const pattern = path.replace(/:[^/]+/g, (match) => {
    paramNames.push(match.slice(1));
    return "([^/]+)";
  });
  const regex = new RegExp(`^${pattern}$`);
  routes.push({ path, regex, paramNames, renderFn, guard: options.guard || null });
}

function matchRoute(hashPath) {
  for (const route of routes) {
    const match = hashPath.match(route.regex);
    if (match) {
      const params = {};
      route.paramNames.forEach((name, idx) => {
        params[name] = decodeURIComponent(match[idx + 1]);
      });
      return { route, params };
    }
  }
  return null;
}

function parseHash() {
  const hash = location.hash.slice(1);
  const raw = hash === "" ? "/" : hash;
  const queryIndex = raw.indexOf("?");
  if (queryIndex === -1) return { path: raw, query: new URLSearchParams() };
  return { path: raw.slice(0, queryIndex), query: new URLSearchParams(raw.slice(queryIndex + 1)) };
}

export function navigate(path) {
  location.hash = path;
}

let lastStarted = 0;
let lastFinished = 0;

async function renderRoute() {
  closeModal();
  const app = document.getElementById("app");
  const { path, query } = parseHash();
  const isPublic = PUBLIC_PATHS.includes(path);

  if (!isLoggedIn() && !isPublic) {
    navigate("/login");
    return;
  }
  if (isLoggedIn() && path === "/login") {
    navigate("/");
    return;
  }
  if (isLoggedIn() && mustChangePassword() && path !== FORCED_PATH) {
    navigate(FORCED_PATH);
    return;
  }

  const matched = matchRoute(path);
  if (!matched) {
    app.innerHTML = `<div class="empty-state">Page introuvable.</div>`;
    return;
  }

  const { route, params } = matched;
  if (route.guard && !route.guard()) {
    app.innerHTML = `<div class="empty-state">Accès non autorisé.</div>`;
    return;
  }

  const token = ++lastStarted;
  app.innerHTML = `<div class="section-loading">Chargement…</div>`;
  try {
    await route.renderFn(app, { ...params, query });
    // Un écran lent qui se termine après le suivant vient de l'écraser : on réaffiche l'écran demandé.
    if (token < lastFinished) {
      renderRoute();
      return;
    }
    lastFinished = token;
  } catch (err) {
    console.error(err);
    app.innerHTML = `<div class="empty-state">Une erreur est survenue : ${String(err.message || err).replace(/</g, "&lt;")}</div>`;
  }
}

export function startRouter() {
  window.addEventListener("hashchange", renderRoute);
  renderRoute();
}

export { renderRoute };
