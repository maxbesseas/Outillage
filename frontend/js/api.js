import { state, clearSession, setSession, reloadSession } from "./state.js";
import { toast } from "./ui.js";
import { navigate } from "./router.js";
import { compressImage } from "./images.js";

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

const MAX_UPLOAD_BYTES = 4 * 1024 * 1024;
const NO_REFRESH_PATHS = ["/auth/login", "/auth/refresh", "/auth/forgot-password", "/auth/reset-password"];

function checkSyncHeaders(res) {
  const excelSync = res.headers.get("X-Excel-Sync");
  if (excelSync && excelSync !== "ok") {
    toast(`Enregistré, mais export Excel échoué : ${excelSync}`, "error");
  }
  const warning = res.headers.get("X-Warning");
  if (warning) {
    toast(`Attention : ${warning}`, "error");
  }
  const notification = res.headers.get("X-Notification");
  if (notification && notification !== "ok") {
    toast(`Enregistré, mais notification magasinier échouée : ${notification}`, "error");
  }
}

let refreshPromise = null;

async function refreshSession() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const previousToken = state.token;
      reloadSession();
      if (state.token && state.token !== previousToken) return true;
      if (!state.refreshToken) return false;
      try {
        const res = await fetch("/auth/refresh", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ refresh_token: state.refreshToken }),
        });
        if (!res.ok) {
          reloadSession();
          return !!state.token && state.token !== previousToken;
        }
        const data = await res.json();
        setSession(data.access_token, data.user, data.refresh_token);
        return true;
      } catch {
        return false;
      }
    })().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

function endSession() {
  clearSession();
  navigate("/login");
}

async function authFetch(path, options = {}, retried = false) {
  const headers = Object.assign({}, options.headers || {});
  if (!(options.body instanceof FormData) && options.body) {
    headers["Content-Type"] = "application/json";
  }
  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
  }

  const res = await fetch(path, { ...options, headers });

  if (res.status === 401 && !NO_REFRESH_PATHS.some((p) => path.startsWith(p))) {
    if (!retried && (await refreshSession())) {
      return authFetch(path, options, true);
    }
    endSession();
    throw new ApiError("Session expirée", 401);
  }

  if (res.status === 403 && res.headers.get("X-Auth-Error") === "password_change_required") {
    if (state.user) setSession(state.token, { ...state.user, must_change_password: true });
    navigate("/mon-profil");
    throw new ApiError("Vous devez changer votre mot de passe avant de continuer", 403);
  }

  if (res.status === 403 && res.headers.get("X-Auth-Error") === "charter_required") {
    navigate("/charte");
    throw new ApiError("Vous devez accepter la charte avant de continuer", 403);
  }

  return res;
}

async function parseBody(res) {
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

const FIELD_LABELS = {
  name: "le nom", unique_code: "le code", purchase_price: "le prix d'achat", daily_rate: "le tarif journalier", purchase_date: "la date d'achat",
  warranty_expiration_date: "la fin de garantie", expiration_date: "la date de péremption", last_control_date: "la date de contrôle",
  to_external_name: "le destinataire", to_external_email: "l'e-mail du destinataire", to_external_phone: "le téléphone du destinataire",
  planned_return_date: "la date de retour", start_datetime: "la date de début", end_datetime_planned: "la date de fin", comment: "le commentaire",
  description: "la description", email: "l'e-mail", phone: "le téléphone", quantity: "la quantité", code: "le code",
};

function validationMessage(detail) {
  const fields = [...new Set(detail.map((d) => FIELD_LABELS[d.loc?.[d.loc.length - 1]]).filter(Boolean))];
  return fields.length ? `Vérifiez ${fields.join(", ")}` : "Données invalides";
}

async function request(path, options = {}) {
  const res = await authFetch(path, options);
  checkSyncHeaders(res);

  const data = await parseBody(res);
  if (!res.ok) {
    const detail = data && data.detail;
    const message = typeof detail === "string" ? detail : Array.isArray(detail) ? validationMessage(detail) : `Erreur ${res.status}`;
    throw new ApiError(message, res.status);
  }
  return data;
}

export { request as apiRequest };

export const api = {
  get(path) {
    return request(path, { method: "GET" });
  },
  post(path, body) {
    return request(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined });
  },
  put(path, body) {
    return request(path, { method: "PUT", body: body !== undefined ? JSON.stringify(body) : undefined });
  },
  patch(path, body) {
    return request(path, { method: "PATCH", body: body !== undefined ? JSON.stringify(body) : undefined });
  },
  delete(path, body) {
    return request(path, { method: "DELETE", body: body !== undefined ? JSON.stringify(body) : undefined });
  },
  async upload(path, file) {
    const toSend = await compressImage(file);
    if (toSend.size > MAX_UPLOAD_BYTES) throw new ApiError("Fichier trop volumineux (4 Mo maximum)", 413);
    const formData = new FormData();
    formData.append("file", toSend);
    return request(path, { method: "POST", body: formData });
  },
  async getPage(path) {
    const res = await authFetch(path, { method: "GET" });
    const data = await parseBody(res);
    if (!res.ok) {
      const detail = data && data.detail;
      throw new ApiError(typeof detail === "string" ? detail : `Erreur ${res.status}`, res.status);
    }
    const total = Number(res.headers.get("X-Total-Count"));
    return { items: data, total: Number.isFinite(total) && res.headers.has("X-Total-Count") ? total : data.length };
  },
  async download(path, fallbackFilename) {
    const res = await authFetch(path, { method: "GET" });
    if (!res.ok) {
      throw new ApiError(`Erreur ${res.status}`, res.status);
    }
    const disposition = res.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : fallbackFilename;

    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  },
};
