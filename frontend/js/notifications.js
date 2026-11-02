import { api } from "./api.js";
import { isLoggedIn } from "./state.js";

let timer = null;

function paint(unread, critical) {
  document.querySelectorAll("[data-bell-badge]").forEach((el) => {
    el.textContent = unread > 99 ? "99+" : String(unread);
    el.classList.toggle("hidden", unread === 0);
    el.classList.toggle("bell-critical", critical > 0);
  });
}

export async function refreshNotificationCount() {
  if (!isLoggedIn() || document.hidden) return;
  try {
    const { unread, critical } = await api.get("/notifications/count");
    paint(unread, critical);
  } catch {
    // le compteur est facultatif : on réessaiera au prochain passage
  }
}

export function startNotificationPolling() {
  if (timer) return;
  refreshNotificationCount();
  timer = setInterval(refreshNotificationCount, 60000);
  document.addEventListener("visibilitychange", refreshNotificationCount);
}

export function stopNotificationPolling() {
  if (timer) clearInterval(timer);
  timer = null;
  document.removeEventListener("visibilitychange", refreshNotificationCount);
  paint(0, 0);
}
