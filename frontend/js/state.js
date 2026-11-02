const STORAGE_KEY = "outillage_session";

function readStored() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { token: null, refreshToken: null, user: null };
    const parsed = JSON.parse(raw);
    return {
      token: parsed.token || null,
      refreshToken: parsed.refreshToken || null,
      user: parsed.user || null,
    };
  } catch {
    return { token: null, refreshToken: null, user: null };
  }
}

export const state = readStored();

export function reloadSession() {
  Object.assign(state, readStored());
}

export function setSession(token, user, refreshToken) {
  state.token = token;
  state.user = user;
  if (refreshToken !== undefined) state.refreshToken = refreshToken;
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ token: state.token, refreshToken: state.refreshToken, user: state.user })
  );
}

const clearHooks = [];

export function onSessionCleared(fn) {
  clearHooks.push(fn);
}

export function clearSession() {
  clearHooks.forEach((fn) => {
    try {
      fn();
    } catch {
      // un nettoyage raté ne doit pas empêcher la déconnexion
    }
  });
  state.token = null;
  state.refreshToken = null;
  state.user = null;
  localStorage.removeItem(STORAGE_KEY);
}

export function isLoggedIn() {
  return !!state.token;
}

export function isAdmin() {
  return !!state.user && state.user.role === "admin";
}

export function isManager() {
  return !!state.user && state.user.role !== "gars_chantier";
}

export function mustChangePassword() {
  return !!state.user && !!state.user.must_change_password;
}
