// Petit pilote CDP (Chrome DevTools Protocol) pour tester l'application dans un vrai navigateur (Edge/Chrome), sans dépendance npm.
import { spawn } from "child_process";
import fs from "fs";
import os from "os";
import path from "path";

export const BASE = process.env.E2E_BASE || "http://127.0.0.1:8124";
const PORT = Number(process.env.E2E_CDP_PORT || 9333);
const BROWSERS = [
  process.env.E2E_BROWSER,
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
].filter(Boolean);

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export class Browser {
  constructor() {
    this.results = [];
    this.consoleProblems = [];
    this.seq = 0;
    this.pending = new Map();
  }

  async start(width = 420, height = 900) {
    const exe = BROWSERS.find((p) => fs.existsSync(p));
    if (!exe) throw new Error("Aucun navigateur Chromium trouvé (définir E2E_BROWSER)");
    this.profile = fs.mkdtempSync(path.join(os.tmpdir(), "fauche-e2e-"));
    this.proc = spawn(exe, ["--headless=new", `--remote-debugging-port=${PORT}`, `--user-data-dir=${this.profile}`, "--no-first-run", "--disable-gpu", `--window-size=${width},${height}`, "about:blank"], { stdio: "ignore" });
    let wsUrl = null;
    for (let i = 0; i < 60 && !wsUrl; i++) {
      try {
        const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
        wsUrl = list.find((t) => t.type === "page")?.webSocketDebuggerUrl;
      } catch {}
      if (!wsUrl) await sleep(250);
    }
    if (!wsUrl) throw new Error("CDP indisponible");
    this.ws = new WebSocket(wsUrl);
    await new Promise((r) => (this.ws.onopen = r));
    this.ws.onmessage = (ev) => this.onMessage(JSON.parse(ev.data));
    await this.send("Page.enable");
    await this.send("Runtime.enable");
    await this.send("Log.enable");
    await this.send("Network.enable");
  }

  onMessage(msg) {
    if (msg.id && this.pending.has(msg.id)) {
      this.pending.get(msg.id)(msg);
      this.pending.delete(msg.id);
      return;
    }
    const p = this.consoleProblems;
    if (msg.method === "Runtime.exceptionThrown") p.push("EXCEPTION " + (msg.params.exceptionDetails.exception?.description || msg.params.exceptionDetails.text));
    if (msg.method === "Runtime.consoleAPICalled" && ["error", "warning"].includes(msg.params.type)) p.push(msg.params.type.toUpperCase() + " " + msg.params.args.map((a) => a.value ?? a.description).join(" "));
    if (msg.method === "Log.entryAdded" && ["error", "warning"].includes(msg.params.entry.level)) p.push("LOG " + msg.params.entry.text + " " + (msg.params.entry.url || ""));
    if (msg.method === "Page.javascriptDialogOpening") this.send("Page.handleJavaScriptDialog", { accept: true, promptText: "test" });
  }

  send(method, params = {}) {
    return new Promise((resolve) => {
      const id = ++this.seq;
      this.pending.set(id, resolve);
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async eval(expression) {
    const res = await this.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (res.result?.exceptionDetails) throw new Error(res.result.exceptionDetails.exception?.description || "erreur d'évaluation");
    return res.result?.result?.value;
  }

  async waitFor(expression, label = "", timeout = 8000) {
    const start = Date.now();
    while (Date.now() - start < timeout) {
      try {
        if (await this.eval(expression)) return true;
      } catch {}
      await sleep(120);
    }
    console.log("   (délai dépassé)", label || expression.slice(0, 60));
    return false;
  }

  goto(url) {
    return this.send("Page.navigate", { url });
  }

  route(hash) {
    return this.eval(`location.hash = ${JSON.stringify(hash)}`);
  }

  text(selector = "#app") {
    return this.eval(`document.querySelector(${JSON.stringify(selector)})?.innerText || ''`);
  }

  setInput(selector, value) {
    return this.eval(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; el.value = ${JSON.stringify(value)}; el.dispatchEvent(new Event('input', {bubbles:true})); el.dispatchEvent(new Event('change', {bubbles:true})); return true; })()`);
  }

  click(selector) {
    return this.eval(`(() => { const el = document.querySelector(${JSON.stringify(selector)}); if (!el) return false; el.click(); return true; })()`);
  }

  submit(selector) {
    return this.eval(`(() => { const f = document.querySelector(${JSON.stringify(selector)}); if (!f) return false; f.requestSubmit(); return true; })()`);
  }

  setOffline(offline) {
    return this.send("Network.emulateNetworkConditions", { offline, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  }

  check(label, ok, extra = "") {
    this.results.push([label, !!ok]);
    console.log(ok ? "OK   " : "FAIL ", label, ok ? "" : extra);
  }

  finish() {
    const failed = this.results.filter(([, ok]) => !ok);
    console.log(`\nTOTAL: ${this.results.length}  FAILED: ${failed.length}`);
    try {
      this.ws.close();
      this.proc.kill();
    } catch {}
    return failed.length;
  }
}

export async function api(method, url, body, token) {
  const res = await fetch(BASE + url, {
    method,
    headers: { "Content-Type": "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let data = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  return { status: res.status, data };
}

export async function login(username, password) {
  const r = await api("POST", "/auth/login", { username, password });
  if (r.status !== 200) throw new Error(`connexion ${username} : ${r.status} ${JSON.stringify(r.data)}`);
  return r.data;
}

export async function loginUi(b, username, password) {
  await b.goto(BASE + "/");
  await b.waitFor("!!document.querySelector('#login-form')", "formulaire de connexion");
  await b.setInput("[name=username]", username);
  await b.setInput("[name=password]", password);
  await b.submit("#login-form");
  await b.waitFor("location.hash !== '#/login' && !!document.querySelector('#app-header:not(.hidden)')", "après connexion");
}
