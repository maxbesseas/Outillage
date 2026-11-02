export function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

let toastTimer = null;

export function toast(message, type = "") {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    document.body.appendChild(el);
  }
  el.className = `toast ${type}`.trim();
  el.textContent = message;
  el.classList.add("visible");

  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.classList.remove("visible");
  }, Math.max(3500, String(message).length * 60));
}

export function formatDate(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "-";
  return d.toLocaleDateString("fr-FR");
}

export function formatDateTime(value) {
  if (!value) return "-";
  const d = new Date(value);
  if (isNaN(d.getTime())) return "-";
  const date = d.toLocaleDateString("fr-FR");
  const time = d.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" });
  return `${date} ${time}`;
}

export function toDatetimeLocal(value) {
  const d = value ? new Date(value) : new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function stateStars(n) {
  const value = Math.max(0, Math.min(5, n ?? 0));
  return "★".repeat(value) + "☆".repeat(5 - value);
}

const AGENCY_STATUS_MAP = {
  disponible: ["green", "Disponible"],
  reserve: ["blue", "Réservé"],
  emprunte: ["red", "Emprunté"],
  reparation: ["orange", "En réparation"],
  hors_service: ["gray", "Hors service"],
  dotation: ["blue", "Dotation"],
};

const LOAN_STATUS_MAP = {
  reserve: ["blue", "Réservé"],
  en_cours: ["orange", "En cours"],
  termine: ["green", "Terminé"],
  annule: ["gray", "Annulé"],
};

const STATE_REASON_MAP = {
  normal: ["green", "Normal"],
  perdu: ["red", "Perdu"],
  endommage: ["orange", "Endommagé"],
  en_reparation: ["orange", "En réparation"],
};

function badgeHtml(color, label) {
  return `<span class="badge badge-${color}"><span class="dot"></span>${escapeHtml(label)}</span>`;
}

export function agencyStatusBadge(status) {
  const [color, label] = AGENCY_STATUS_MAP[status] || ["gray", status];
  return badgeHtml(color, label);
}

export function loanStatusBadge(status) {
  const [color, label] = LOAN_STATUS_MAP[status] || ["gray", status];
  return badgeHtml(color, label);
}

export function stateReasonBadge(reason) {
  const [color, label] = STATE_REASON_MAP[reason] || ["gray", reason];
  return badgeHtml(color, label);
}

export function stateHistoryCard(h, authorName) {
  const stateChange = `${h.old_state ?? "-"}/5 → ${h.new_state}/5`;
  const statusChange =
    h.old_status !== h.new_status
      ? `<div class="card-sub">Statut : ${escapeHtml(h.old_status || "-")} → ${escapeHtml(h.new_status || "-")}</div>`
      : "";
  return `
    <div class="card">
      <div class="card-row">
        <div class="card-title">${escapeHtml(stateChange)}</div>
        <div class="card-sub">${escapeHtml(formatDateTime(h.changed_at))}</div>
      </div>
      <div class="card-meta">
        <span>${escapeHtml(h.source)}</span>
        <span>${escapeHtml(authorName || "-")}</span>
      </div>
      ${statusChange}
      ${h.comment ? `<div class="card-sub">${escapeHtml(h.comment)}</div>` : ""}
    </div>
  `;
}

export function personColor(userId) {
  const hue = (Number(userId) * 137.508) % 360;
  return `hsl(${hue}, 65%, 55%)`;
}

export function openModal(innerHtml, options = {}) {
  closeModal();
  const backdrop = document.createElement("div");
  backdrop.className = "modal-backdrop";
  backdrop.id = "modal-backdrop";
  backdrop.innerHTML = `<div class="modal">${innerHtml}</div>`;

  backdrop.addEventListener("click", (e) => {
    if (e.target === backdrop) closeModal();
  });

  document.body.appendChild(backdrop);
  document.body.classList.add("modal-open");

  if (options.onMount) options.onMount(backdrop);
  return backdrop;
}

export function closeModal() {
  const existing = document.getElementById("modal-backdrop");
  if (existing) existing.remove();
  document.body.classList.remove("modal-open");
}

/** Remplace window.confirm() par une modale. Résout à true/false, ne rejette jamais. */
export function confirmDialog(message, { danger = false, confirmLabel = "Confirmer", cancelLabel = "Annuler" } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      closeModal();
      resolve(value);
    };
    openModal(
      `<div class="modal-header"><div class="card-title">Confirmation</div></div>
      <p>${escapeHtml(message)}</p>
      <div class="card-actions">
        <button class="btn ${danger ? "btn-danger" : "btn-primary"}" id="confirm-yes">${escapeHtml(confirmLabel)}</button>
        <button class="btn" id="confirm-no">${escapeHtml(cancelLabel)}</button>
      </div>`,
      {
        onMount: (root) => {
          root.querySelector("#confirm-yes").focus();
          root.querySelector("#confirm-yes").addEventListener("click", () => finish(true));
          root.querySelector("#confirm-no").addEventListener("click", () => finish(false));
          root.addEventListener("click", (e) => {
            if (e.target.id === "modal-backdrop") finish(false);
          });
        },
      }
    );
  });
}

/** Remplace window.prompt() par une modale. Résout à la chaîne saisie, ou null si annulé. */
export function promptDialog(message, { placeholder = "", initial = "", confirmLabel = "Valider" } = {}) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      closeModal();
      resolve(value);
    };
    openModal(
      `<div class="modal-header"><div class="card-title">${escapeHtml(message)}</div></div>
      <form id="prompt-form" class="form-grid">
        <input type="text" id="prompt-input" value="${escapeHtml(initial)}" placeholder="${escapeHtml(placeholder)}" autocomplete="off"/>
        <div class="card-actions">
          <button type="submit" class="btn btn-primary">${escapeHtml(confirmLabel)}</button>
          <button type="button" class="btn" id="prompt-cancel">Annuler</button>
        </div>
      </form>`,
      {
        onMount: (root) => {
          const input = root.querySelector("#prompt-input");
          input.focus();
          root.querySelector("#prompt-form").addEventListener("submit", (e) => {
            e.preventDefault();
            finish(input.value);
          });
          root.querySelector("#prompt-cancel").addEventListener("click", () => finish(null));
          root.addEventListener("click", (e) => {
            if (e.target.id === "modal-backdrop") finish(null);
          });
        },
      }
    );
  });
}

export function wireImageFallbacks(root = document) {
  root.querySelectorAll("img[data-fallback-hide]").forEach((img) => {
    const hide = () => {
      img.style.display = "none";
    };
    img.addEventListener("error", hide, { once: true });
    if (img.complete && img.naturalWidth === 0) hide();
  });
}
