const CACHE_NAME = "outillage-shell-v42";

const APP_SHELL = [
  "/",
  "/index.html",
  "/manifest.webmanifest",
  "/css/style.css",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
  "/icons/fauche-logo-full.png",
  "/js/main.js",
  "/js/router.js",
  "/js/theme.js",
  "/js/globalSearch.js",
  "/js/state.js",
  "/js/api.js",
  "/js/ui.js",
  "/js/roles.js",
  "/js/icons.js",
  "/js/barcode.js",
  "/js/scanner.js",
  "/js/usersCache.js",
  "/js/toolHistory.js",
  "/js/toolTypeSuggestions.js",
  "/js/reservationForm.js",
  "/js/assistant.js",
  "/js/agencies.js",
  "/js/notifications.js",
  "/js/push.js",
  "/js/images.js",
  "/js/signaturePad.js",
  "/js/inspectionForm.js",
  "/js/loanActions.js",
  "/js/departureWizard.js",
  "/js/offlineQueue.js",
  "/js/qr.js",
  "/js/reportProblem.js",
  "/js/toolExtras.js",
  "/js/views/login.js",
  "/js/views/toolBoard.js",
  "/fonts/barlow-condensed-latin-600-normal.woff2",
  "/fonts/barlow-condensed-latin-700-normal.woff2",
  "/js/views/dashboard.js",
  "/js/views/personalTools.js",
  "/js/views/agencyTools.js",
  "/js/views/loans.js",
  "/js/views/transfers.js",
  "/js/views/peerTransfers.js",
  "/js/views/users.js",
  "/js/views/financial.js",
  "/js/views/inventory.js",
  "/js/views/epi.js",
  "/js/views/labels.js",
  "/js/views/warranty.js",
  "/js/views/settings.js",
  "/js/views/profile.js",
  "/js/views/forgotPassword.js",
  "/js/views/resetPassword.js",
  "/js/views/audit.js",
  "/js/views/jobs.js",
  "/js/views/notifications.js",
  "/js/views/appSettings.js",
  "/js/views/controls.js",
  "/js/views/policies.js",
  "/js/views/calibrations.js",
  "/js/views/qualifications.js",
  "/js/views/planning.js",
  "/js/views/myLoans.js",
  "/js/views/maintenance.js",
  "/js/views/stock.js",
  "/js/views/toolSheet.js",
  "/js/views/scan.js",
  "/js/views/sites.js",
  "/js/views/usage.js",
  "/js/views/imports.js",
  "/js/views/backups.js",
  "/js/views/assistantInsights.js",
  "/js/views/financeAdvanced.js",
];

const API_PREFIXES = [
  "/auth",
  "/users",
  "/personal-tools",
  "/agency-tools",
  "/loans",
  "/transfers",
  "/peer-transfers",
  "/epi",
  "/uploads",
  "/settings",
  "/state-history",
  "/assistant",
  "/agencies",
  "/audit-log",
  "/admin",
  "/cron",
  "/notifications",
  "/push",
  "/dashboard",
  "/inspections",
  "/inspection-policies",
  "/inspection-templates",
  "/calibrations",
  "/qualifications",
  "/qualification-types",
  "/tool-requirements",
  "/kits",
  "/waitlist",
  "/blackouts",
  "/reservation-rules",
  "/agency-transfers",
  "/calendar",
  "/tools",
  "/search",
  "/tool-photos",
  "/maintenance-tickets",
  "/exit-requests",
  "/stock",
  "/sites",
  "/stats",
  "/finance",
  "/losses",
  "/exports",
  "/api-keys",
  "/reports",
  "/imports",
  "/gdpr",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))))
      .then(() => self.clients.claim())
  );
});

function isApiPath(pathname) {
  return API_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

function isSourcePath(pathname) {
  return pathname === "/" || pathname.endsWith(".js") || pathname.endsWith(".css") || pathname.endsWith(".html");
}

self.addEventListener("fetch", (event) => {
  const url = new URL(event.request.url);
  if (url.origin !== location.origin) return;

  if (isApiPath(url.pathname)) {
    event.respondWith(fetch(event.request));
    return;
  }

  if (isSourcePath(url.pathname)) {
    event.respondWith(
      fetch(event.request)
        .then((res) => {
          const clone = res.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
          return res;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) return cached;
      return fetch(event.request).then((res) => {
        const clone = res.clone();
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone));
        return res;
      });
    })
  );
});

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "Fauché — Gestion Outillage", {
      body: data.body || "",
      icon: "/icons/icon-192.png",
      badge: "/icons/icon-192.png",
      tag: data.tag,
      data: { url: data.url || "#/notifications" },
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = "/" + ((event.notification.data && event.notification.data.url) || "#/notifications");
  event.waitUntil(
    clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const client of windows) {
        if ("focus" in client) {
          client.navigate(target);
          return client.focus();
        }
      }
      return clients.openWindow(target);
    })
  );
});
