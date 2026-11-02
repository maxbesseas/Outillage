import { api, ApiError } from "../api.js";
import { escapeHtml, formatDateTime, toast } from "../ui.js";
import { navigate } from "../router.js";
import { refreshNotificationCount } from "../notifications.js";

const PAGE_SIZE = 30;
const SEVERITY = { critical: ["red", "Critique"], warning: ["orange", "À traiter"], info: ["blue", "Info"] };

let unreadOnly = false;

function card(n) {
  const [color, label] = SEVERITY[n.severity] || SEVERITY.info;
  return `
    <div class="card notification ${n.read_at ? "notification-read" : ""}" data-id="${n.id}" data-link="${escapeHtml(n.link || "")}">
      <div class="card-row">
        <div class="card-title">${escapeHtml(n.title)}</div>
        <span class="badge badge-${color}"><span class="dot"></span>${label}</span>
      </div>
      ${n.body ? `<div class="card-sub">${escapeHtml(n.body)}</div>` : ""}
      <div class="card-meta"><span>${escapeHtml(formatDateTime(n.created_at))}</span>${n.read_at ? "<span>Lue</span>" : ""}</div>
    </div>`;
}

export async function renderNotifications(app) {
  app.innerHTML = `
    <div class="section-header">
      <h1>Alertes</h1>
      <div class="section-links"><button class="btn btn-sm" id="read-all">Tout marquer comme lu</button></div>
    </div>
    <div class="tag-row" id="notif-tabs">
      <button data-only="0" class="${unreadOnly ? "" : "active"}">Toutes</button>
      <button data-only="1" class="${unreadOnly ? "active" : ""}">Non lues</button>
    </div>
    <div id="notif-list"></div>
    <div class="load-more"><button class="btn hidden" id="notif-more">Charger plus</button></div>
  `;

  const list = document.getElementById("notif-list");
  const more = document.getElementById("notif-more");
  let loaded = 0;

  async function load(reset) {
    if (reset) {
      loaded = 0;
      list.innerHTML = "";
    }
    try {
      const { items, total } = await api.getPage(`/notifications?limit=${PAGE_SIZE}&offset=${loaded}&unread_only=${unreadOnly}`);
      list.insertAdjacentHTML("beforeend", items.map(card).join(""));
      loaded += items.length;
      more.classList.toggle("hidden", loaded >= total);
      if (!total) list.innerHTML = `<div class="empty-state">${unreadOnly ? "Aucune alerte non lue." : "Aucune alerte pour le moment."}</div>`;
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Erreur", "error");
    }
  }

  list.addEventListener("click", async (e) => {
    const el = e.target.closest(".notification");
    if (!el) return;
    try {
      await api.post(`/notifications/${el.dataset.id}/read`);
      refreshNotificationCount();
    } catch {
      // la lecture reste facultative
    }
    if (el.dataset.link) navigate(el.dataset.link.replace(/^#/, ""));
    else el.classList.add("notification-read");
  });

  document.querySelectorAll("#notif-tabs button").forEach((btn) =>
    btn.addEventListener("click", () => {
      unreadOnly = btn.dataset.only === "1";
      renderNotifications(app);
    })
  );
  document.getElementById("read-all").addEventListener("click", async () => {
    await api.post("/notifications/read-all");
    refreshNotificationCount();
    load(true);
  });
  more.addEventListener("click", () => load(false));

  await load(true);
}
