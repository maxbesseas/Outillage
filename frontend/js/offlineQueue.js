// File d'attente hors ligne (IndexedDB) + cache de lecture. Les écritures rejouées portent un
// en-tête Idempotency-Key : le serveur ne les applique qu'une fois même si la réponse s'est perdue.
import { apiRequest, ApiError } from "./api.js";
import { state, onSessionCleared } from "./state.js";
import { toast } from "./ui.js";

const DB_NAME = "fauche-offline";
const QUEUE = "queue";
const CACHE = "cache";
const listeners = new Set();
let flushing = false;

function openDb() {
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, 1);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(QUEUE)) db.createObjectStore(QUEUE, { keyPath: "id", autoIncrement: true });
      if (!db.objectStoreNames.contains(CACHE)) db.createObjectStore(CACHE, { keyPath: "key" });
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

async function tx(store, mode, fn) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const t = db.transaction(store, mode);
    const result = fn(t.objectStore(store));
    t.oncomplete = () => {
      db.close();
      resolve(result && "result" in result ? result.result : result);
    };
    t.onerror = () => {
      db.close();
      reject(t.error);
    };
  });
}

function notify() {
  pendingCount().then((n) => listeners.forEach((fn) => fn(n)));
}

export function onQueueChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

function newKey() {
  return crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export async function listQueue() {
  const all = await tx(QUEUE, "readonly", (s) => s.getAll());
  return (all || []).filter((e) => e.username === state.user?.username);
}

export async function pendingCount() {
  try {
    return (await listQueue()).length;
  } catch {
    return 0;
  }
}

async function enqueue(op) {
  const entry = {
    username: state.user?.username,
    label: op.label,
    method: op.method,
    path: op.path,
    body: op.body ?? null,
    followUp: op.followUp || null,
    key: newKey(),
    created: new Date().toISOString(),
    status: "pending",
    error: null,
  };
  await tx(QUEUE, "readwrite", (s) => s.add(entry));
  notify();
  return { queued: true };
}

function isNetworkError(err) {
  return err instanceof TypeError || (err && err.name === "TypeError");
}

async function sendEntry(entry) {
  const opts = { method: entry.method, headers: { "Idempotency-Key": entry.key } };
  if (entry.body !== null && entry.body !== undefined) opts.body = JSON.stringify(entry.body);
  const result = await apiRequest(entry.path, opts);
  if (entry.followUp && entry.followUp.file && result && result.id !== undefined) {
    const form = new FormData();
    form.append("file", entry.followUp.file, entry.followUp.file.name || "photo.jpg");
    await apiRequest(entry.followUp.path.replace("{id}", result.id), {
      method: "POST",
      body: form,
      headers: { "Idempotency-Key": `${entry.key}-file` },
    });
  }
  return result;
}

/** Envoie tout de suite si possible, sinon met en file d'attente (jamais pour les erreurs métier). */
export async function queueOrSend(op) {
  if (!navigator.onLine) return enqueue(op);
  const entry = { ...op, key: newKey() };
  try {
    const data = await sendEntry(entry);
    return { queued: false, data, id: data && data.id };
  } catch (err) {
    if (isNetworkError(err)) return enqueue(op);
    throw err;
  }
}

/** Rejoue la file dans l'ordre. Les refus du serveur deviennent des conflits à traiter à la main. */
export async function flushQueue({ silent = false } = {}) {
  if (flushing || !navigator.onLine || !state.token) return { sent: 0, conflicts: 0 };
  flushing = true;
  let sent = 0;
  let conflicts = 0;
  try {
    for (const entry of await listQueue()) {
      if (entry.status === "conflict") continue;
      try {
        await sendEntry(entry);
        await tx(QUEUE, "readwrite", (s) => s.delete(entry.id));
        sent++;
      } catch (err) {
        if (isNetworkError(err)) break;
        const message = err instanceof ApiError ? err.message : "Erreur";
        if (err instanceof ApiError && err.status === 401) break;
        await tx(QUEUE, "readwrite", (s) => s.put({ ...entry, status: "conflict", error: message }));
        conflicts++;
      }
    }
  } finally {
    flushing = false;
    notify();
  }
  if (!silent && (sent || conflicts)) {
    if (sent) toast(`${sent} action(s) hors ligne synchronisée(s)`, "success");
    if (conflicts) toast(`${conflicts} action(s) refusée(s) par le serveur : à vérifier dans Synchronisation`, "error");
  }
  return { sent, conflicts };
}

export async function retryEntry(id) {
  const all = await tx(QUEUE, "readonly", (s) => s.getAll());
  const entry = (all || []).find((e) => e.id === id);
  if (entry) await tx(QUEUE, "readwrite", (s) => s.put({ ...entry, status: "pending", error: null }));
  return flushQueue();
}

export async function discardEntry(id) {
  await tx(QUEUE, "readwrite", (s) => s.delete(id));
  notify();
}

// ---- cache de lecture (consultation hors ligne des fiches et listes déjà vues)
export async function cachePut(key, value) {
  try {
    await tx(CACHE, "readwrite", (s) => s.put({ key: `${state.user?.username}:${key}`, value, at: Date.now() }));
  } catch {
    // le cache est facultatif
  }
}

export async function cacheGet(key) {
  try {
    const row = await tx(CACHE, "readonly", (s) => s.get(`${state.user?.username}:${key}`));
    return row ? { value: row.value, at: row.at } : null;
  } catch {
    return null;
  }
}

/** GET avec repli sur le cache quand le réseau est coupé. Renvoie {data, offline, at}. */
export async function cachedGet(path, api) {
  try {
    const data = await api.get(path);
    cachePut(path, data);
    return { data, offline: false };
  } catch (err) {
    if (!isNetworkError(err)) throw err;
    const hit = await cacheGet(path);
    if (hit) return { data: hit.value, offline: true, at: hit.at };
    throw new ApiError("Hors ligne et aucune copie locale de cette page", 0);
  }
}

async function clearReadCache() {
  try {
    await tx(CACHE, "readwrite", (s) => s.clear());
  } catch {
    // rien à faire
  }
}
onSessionCleared(clearReadCache);

let started = false;

export function startOfflineSync() {
  if (started) return;
  started = true;
  window.addEventListener("online", () => flushQueue());
  setInterval(() => flushQueue({ silent: true }), 60000);
  flushQueue({ silent: true });
  notify();
}
