import { api, ApiError } from "../api.js";
import {
  escapeHtml,
  formatDate,
  formatDateTime,
  loanStatusBadge,
  personColor,
  toast,
  openModal,
  closeModal,
} from "../ui.js";
import { state, isManager } from "../state.js";
import { getAllUsers, getUserName } from "../usersCache.js";
import { openToolHistory } from "../toolHistory.js";
import { openReserveForm } from "../reservationForm.js";
import { icon } from "../icons.js";
import { drawMine } from "./myLoans.js";
import { openLoanDetailModal } from "../loanActions.js";

const MAX_EVENTS = { day: 50, week: 6, month: 3 };

let activeTab = "calendar";
let calMode = "month";
let calDate = new Date();
let calScope = "agency";
let filterType = "";
let filterName = "";
let filterCode = "";
let mineFilter = "active";

function startOfDay(d) {
  const r = new Date(d);
  r.setHours(0, 0, 0, 0);
  return r;
}

function addDays(d, n) {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

function startOfWeek(d) {
  const r = startOfDay(d);
  const day = (r.getDay() + 6) % 7;
  return addDays(r, -day);
}

function capitalize(s) {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function overlaps(dayStart, dayEnd, evStart, evEnd) {
  return evStart < dayEnd && evEnd > dayStart;
}

export async function renderLoans(app) {
  await draw(app);
}

async function draw(app) {
  app.innerHTML = `
    <div class="section-header"><h1>Réservations</h1></div>
    <div class="tag-row" id="loan-tabs">
      <button data-tab="calendar" class="${activeTab === "calendar" ? "active" : ""}">Calendrier</button>
      <button data-tab="mine" class="${activeTab === "mine" ? "active" : ""}">Mes réservations</button>
    </div>
    <div id="loan-body"></div>
  `;

  document.querySelectorAll("#loan-tabs button").forEach((btn) => {
    btn.addEventListener("click", () => {
      activeTab = btn.dataset.tab;
      draw(app);
    });
  });

  const body = document.getElementById("loan-body");
  if (activeTab === "calendar") {
    await drawCalendar(body);
  } else {
    await drawMine(body);
  }
}

async function drawCalendar(container) {
  const [tools, users] = await Promise.all([api.get("/agency-tools"), getAllUsers()]);

  const names = filterType ? [...new Set(tools.filter((t) => t.type === filterType).map((t) => t.name))].sort() : [];
  const codes =
    filterType && filterName
      ? tools.filter((t) => t.type === filterType && t.name === filterName).map((t) => ({ id: t.id, code: t.unique_code }))
      : [];

  const types = [...new Set(tools.map((t) => t.type).filter(Boolean))].sort();

  container.innerHTML = `
    <div class="filter-bar">
      <select id="cal-type">
        <option value="">Tous types</option>
        ${types.map((t) => `<option value="${escapeHtml(t)}" ${t === filterType ? "selected" : ""}>${escapeHtml(t)}</option>`).join("")}
      </select>
      <select id="cal-name" ${filterType ? "" : "disabled"}>
        <option value="">Tous noms</option>
        ${names.map((n) => `<option value="${escapeHtml(n)}" ${n === filterName ? "selected" : ""}>${escapeHtml(n)}</option>`).join("")}
      </select>
      <select id="cal-code" ${filterName ? "" : "disabled"}>
        <option value="">Tout outil</option>
        ${codes.map((c) => `<option value="${c.id}" ${String(c.id) === filterCode ? "selected" : ""}>${escapeHtml(c.code)}</option>`).join("")}
      </select>
      <select id="cal-scope">
        <option value="agency" ${calScope === "agency" ? "selected" : ""}>Toute l'agence</option>
        ${isManager() ? `<option value="team" ${calScope === "team" ? "selected" : ""}>Mon équipe</option>` : ""}
        <option value="mine" ${calScope === "mine" ? "selected" : ""}>Moi seulement</option>
      </select>
    </div>

    <div class="cal-toolbar">
      <div class="cal-nav">
        <button class="btn btn-sm" id="cal-prev">${icon("chevronLeft", { size: 16 })}</button>
        <div class="cal-title" id="cal-title"></div>
        <button class="btn btn-sm" id="cal-next">${icon("chevronRight", { size: 16 })}</button>
        <button class="btn btn-sm" id="cal-today">Aujourd'hui</button>
      </div>
      <div class="cal-modes tag-row" style="margin:0;">
        <button data-mode="day" class="${calMode === "day" ? "active" : ""}">Jour</button>
        <button data-mode="week" class="${calMode === "week" ? "active" : ""}">Semaine</button>
        <button data-mode="month" class="${calMode === "month" ? "active" : ""}">Mois</button>
      </div>
    </div>

    <div class="cal-legend" id="cal-legend"></div>

    <div class="cal-layout">
      <div id="cal-grid-wrap"></div>
      <div class="cal-side">
        <h3>Outils disponibles</h3>
        <div id="cal-side-list"></div>
      </div>
    </div>
  `;

  document.getElementById("cal-type").addEventListener("change", (e) => {
    filterType = e.target.value;
    filterName = "";
    filterCode = "";
    drawCalendar(container);
  });
  document.getElementById("cal-name").addEventListener("change", (e) => {
    filterName = e.target.value;
    filterCode = "";
    drawCalendar(container);
  });
  document.getElementById("cal-code").addEventListener("change", (e) => {
    filterCode = e.target.value;
    drawCalendar(container);
  });
  document.getElementById("cal-scope").addEventListener("change", (e) => {
    calScope = e.target.value;
    drawCalendar(container);
  });

  document.getElementById("cal-prev").addEventListener("click", () => {
    shiftCalDate(-1);
    drawCalendar(container);
  });
  document.getElementById("cal-next").addEventListener("click", () => {
    shiftCalDate(1);
    drawCalendar(container);
  });
  document.getElementById("cal-today").addEventListener("click", () => {
    calDate = new Date();
    drawCalendar(container);
  });
  document.querySelectorAll(".cal-modes button").forEach((btn) => {
    btn.addEventListener("click", () => {
      calMode = btn.dataset.mode;
      drawCalendar(container);
    });
  });

  await renderCalendarBody(container, tools, users);
}

function shiftCalDate(dir) {
  if (calMode === "day") calDate = addDays(calDate, dir);
  else if (calMode === "week") calDate = addDays(calDate, dir * 7);
  else {
    const d = new Date(calDate);
    d.setMonth(d.getMonth() + dir);
    calDate = d;
  }
}

async function renderCalendarBody(container, tools, users) {
  const loans = await api.get(`/loans?scope=${calScope}`);
  let transfers = [];
  if (!filterType && !filterName && !filterCode) {
    transfers = await api.get(`/transfers?scope=${calScope}`);
  }

  const activeLoans = loans.filter((l) => ["en_cours", "reserve", "attente_validation"].includes(l.status));
  const activeTransfers = transfers.filter((t) => t.status === "en_cours" && t.tool_id);
  const blackouts = await api.get("/blackouts");

  let scopedTools = tools;
  if (filterType) scopedTools = scopedTools.filter((t) => t.type === filterType);
  if (filterName) scopedTools = scopedTools.filter((t) => t.name === filterName);
  if (filterCode) scopedTools = scopedTools.filter((t) => String(t.id) === filterCode);

  const scopedToolIds = new Set(scopedTools.map((t) => t.id));
  const relevantLoans = filterType || filterName || filterCode ? activeLoans.filter((l) => scopedToolIds.has(l.tool_id)) : activeLoans;

  const peopleIds = new Set([...relevantLoans.map((l) => l.borrower_id), ...activeTransfers.map((t) => t.from_user_id)]);
  document.getElementById("cal-legend").innerHTML = [...peopleIds]
    .map(
      (id) => `
    <div class="cal-legend-item"><span class="cal-legend-dot" style="background:${personColor(id)}"></span>${escapeHtml(getUserName(id))}</div>
  `
    )
    .join("");

  const availableTools = scopedTools.filter((t) => t.status === "disponible");
  document.getElementById("cal-side-list").innerHTML = availableTools.length
    ? availableTools
        .map(
          (t) => `
      <div class="card" style="padding:0.6rem 0.7rem;">
        <div class="card-row">
          <div class="card-sub">${escapeHtml(t.name)}</div>
          <button class="btn btn-sm" data-reserve-id="${t.id}">${icon("plus", { size: 14 })}</button>
        </div>
      </div>`
        )
        .join("")
    : `<div class="empty-state">Aucun outil disponible.</div>`;

  document.querySelectorAll("[data-reserve-id]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tool = tools.find((t) => t.id === Number(btn.dataset.reserveId));
      openReserveForm(tool, () => renderCalendarBody(container, tools, users));
    });
  });

  let days = [];
  let titleText = "";

  if (calMode === "day") {
    days = [startOfDay(calDate)];
    titleText = capitalize(calDate.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", year: "numeric" }));
  } else if (calMode === "week") {
    const start = startOfWeek(calDate);
    days = Array.from({ length: 7 }, (_, i) => addDays(start, i));
    titleText = `${formatDate(days[0])} — ${formatDate(days[6])}`;
  } else {
    const monthStart = new Date(calDate.getFullYear(), calDate.getMonth(), 1);
    const gridStart = startOfWeek(monthStart);
    days = Array.from({ length: 42 }, (_, i) => addDays(gridStart, i));
    titleText = capitalize(calDate.toLocaleDateString("fr-FR", { month: "long", year: "numeric" }));
  }

  document.getElementById("cal-title").textContent = titleText;

  const gridClass = calMode === "month" ? "cal-grid" : calMode === "week" ? "cal-grid" : "cal-grid cal-day";
  const weekdayHeaders =
    calMode !== "day"
      ? ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
          .map((d) => `<div class="cal-cell-head" style="background:var(--surface);padding:0.3rem;">${d}</div>`)
          .join("")
      : "";

  const maxEvents = MAX_EVENTS[calMode];

  const cellsHtml = days
    .map((day) => {
      const dayStart = startOfDay(day);
      const dayEnd = addDays(dayStart, 1);
      const outside = calMode === "month" && day.getMonth() !== calDate.getMonth();

      const loanEvents = relevantLoans
        .filter((l) => overlaps(dayStart, dayEnd, new Date(l.start_datetime), new Date(l.end_datetime_planned)))
        .map((l) => ({ kind: "loan", data: l, personId: l.borrower_id }));

      const transferEvents = activeTransfers
        .filter((t) => {
          const start = new Date(t.transfer_date);
          const end = t.planned_return_date ? new Date(t.planned_return_date) : addDays(start, 1);
          return overlaps(dayStart, dayEnd, start, end);
        })
        .map((t) => ({ kind: "transfer", data: t, personId: t.from_user_id }));

      const filtered = filterType || filterName || filterCode;
      const blackoutEvents = blackouts
        .filter((b) => (!filtered || scopedToolIds.has(b.tool_id)) && overlaps(dayStart, dayEnd, new Date(b.start_datetime), new Date(b.end_datetime)))
        .map((b) => ({ kind: "blackout", data: b, personId: 0 }));

      const events = [...loanEvents, ...transferEvents, ...blackoutEvents];
      const shown = events.slice(0, maxEvents);
      const overflow = events.length - shown.length;

      const chips = shown
        .map((ev) => {
          const color = personColor(ev.personId);
          const toolName = tools.find((t) => t.id === (ev.data.tool_id ?? -1))?.name || "";
          const label =
            ev.kind === "loan"
              ? `${getUserName(ev.data.borrower_id)} · ${toolName}`
              : ev.kind === "blackout"
                ? `Indisponible · ${toolName} (${ev.data.reason})`
                : `${getUserName(ev.data.from_user_id)} → ${ev.data.to_external_name}`;
          const chipClass =
            ev.kind === "transfer" ? "cal-chip-external" : ev.kind === "blackout" ? "cal-chip-blackout"
              : ev.data.status === "reserve" ? "cal-chip-reserved" : ev.data.status === "attente_validation" ? "cal-chip-pending" : "";
          return `<div class="cal-chip ${chipClass}" style="border-left-color:${color}" data-ev-kind="${ev.kind}" data-ev-id="${ev.data.id}">${escapeHtml(label)}</div>`;
        })
        .join("");

      return `
        <div class="cal-cell ${outside ? "cal-outside" : ""}">
          <div class="cal-cell-head">
            <span>${day.getDate()}</span>
            <button data-quick-day="${day.toISOString()}">${icon("plus", { size: 14 })}</button>
          </div>
          <div class="cal-chips">
            ${chips}
            ${overflow > 0 ? `<div class="cal-more" data-more-day="${day.toISOString()}">+${overflow} autres</div>` : ""}
          </div>
        </div>
      `;
    })
    .join("");

  document.getElementById("cal-grid-wrap").innerHTML = `
    <div class="${gridClass}">
      ${weekdayHeaders}
      ${cellsHtml}
    </div>
  `;

  document.querySelectorAll("[data-quick-day]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const day = new Date(btn.dataset.quickDay);
      if (scopedTools.length === 1) {
        openReserveForm(scopedTools[0], () => renderCalendarBody(container, tools, users), day);
      } else if (availableTools.length) {
        openToolPicker(availableTools, (tool) => openReserveForm(tool, () => renderCalendarBody(container, tools, users), day));
      } else {
        toast("Aucun outil disponible pour ce filtre", "error");
      }
    });
  });

  document.querySelectorAll("[data-ev-kind]").forEach((chip) => {
    chip.addEventListener("click", () => {
      const kind = chip.dataset.evKind;
      const id = Number(chip.dataset.evId);
      if (kind === "blackout") return;
      if (kind === "loan") {
        const loan = relevantLoans.find((l) => l.id === id);
        openLoanDetail(loan, tools, () => renderCalendarBody(container, tools, users));
      } else {
        const transfer = activeTransfers.find((t) => t.id === id);
        openTransferDetail(transfer, () => renderCalendarBody(container, tools, users));
      }
    });
  });

  document.querySelectorAll("[data-more-day]").forEach((el) => {
    el.addEventListener("click", () => {
      const day = new Date(el.dataset.moreDay);
      const dayStart = startOfDay(day);
      const dayEnd = addDays(dayStart, 1);
      const dayLoans = relevantLoans.filter((l) => overlaps(dayStart, dayEnd, new Date(l.start_datetime), new Date(l.end_datetime_planned)));
      openDayListModal(day, dayLoans, tools);
    });
  });
}

function openToolPicker(availableTools, onPick) {
  const html = `
    <div class="modal-header">
      <div class="card-title">Choisir un outil</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <div class="form-grid">
      ${availableTools
        .map((t) => `<button class="btn btn-block" data-pick="${t.id}">${escapeHtml(t.name)}</button>`)
        .join("")}
    </div>
  `;
  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      root.querySelectorAll("[data-pick]").forEach((btn) => {
        btn.addEventListener("click", () => {
          const tool = availableTools.find((t) => t.id === Number(btn.dataset.pick));
          closeModal();
          onPick(tool);
        });
      });
    },
  });
}

function openDayListModal(day, dayLoans, tools) {
  const html = `
    <div class="modal-header">
      <div class="card-title">${capitalize(day.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long" }))}</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <div class="modal-body">
      ${dayLoans
        .map(
          (l) => `
        <div class="card">
          <div class="card-title">${escapeHtml(getUserName(l.borrower_id))} · ${escapeHtml(tools.find((t) => t.id === l.tool_id)?.name || "")}</div>
          <div class="card-sub">${formatDateTime(l.start_datetime)} → ${formatDateTime(l.end_datetime_planned)}</div>
        </div>`
        )
        .join("")}
    </div>
  `;
  openModal(html, {
    onMount: (root) => root.querySelector("#form-close").addEventListener("click", closeModal),
  });
}

function openLoanDetail(loan, tools, onDone) {
  openLoanDetailModal(loan, tools.find((t) => t.id === loan.tool_id), onDone);
}

function openTransferDetail(transfer, onDone) {
  const canAct = isManager() || transfer.from_user_id === state.user.id;
  const html = `
    <div class="modal-header">
      <div class="card-title">Prêt externe</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <div class="card-meta" style="margin-bottom:0.5rem;">
      <span>De : ${escapeHtml(getUserName(transfer.from_user_id))}</span>
      <span>Vers : ${escapeHtml(transfer.to_external_name)}</span>
      <span>Type : ${escapeHtml(transfer.to_external_type)}</span>
    </div>
    ${transfer.to_external_company ? `<div class="card-sub">Entreprise : ${escapeHtml(transfer.to_external_company)}</div>` : ""}
    <div class="card-sub">Prêté le ${formatDate(transfer.transfer_date)}${transfer.planned_return_date ? ` · retour prévu ${formatDate(transfer.planned_return_date)}` : ""}</div>
    ${transfer.comment ? `<div class="card-sub">${escapeHtml(transfer.comment)}</div>` : ""}
    <div class="card-actions">
      ${canAct ? '<button class="btn btn-sm" id="detail-return">Rendre l\'outil</button>' : ""}
      <button class="btn btn-sm" id="detail-history">Historique</button>
    </div>
  `;
  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      const returnBtn = root.querySelector("#detail-return");
      if (returnBtn) {
        returnBtn.addEventListener("click", () => {
          closeModal();
          openTransferReturnForm(transfer, onDone);
        });
      }
      root.querySelector("#detail-history").addEventListener("click", () => openToolHistory("personal", transfer.tool_id, "Prêt externe"));
    },
  });
}

function openTransferReturnForm(transfer, onDone) {
  const html = `
    <div class="modal-header">
      <div class="card-title">Retour de prêt externe</div>
      <button class="btn btn-ghost btn-sm" id="form-close">Fermer</button>
    </div>
    <form id="transfer-return-form" class="form-grid">
      <div class="field">
        <label>État constaté au retour (0-5)</label>
        <input type="number" name="state_after" min="0" max="5" value="${transfer.state_before ?? 5}" required/>
      </div>
      <div class="field">
        <label>Commentaire</label>
        <textarea name="comment" rows="2"></textarea>
      </div>
      <button type="submit" class="btn btn-primary">Confirmer le retour</button>
    </form>
  `;
  openModal(html, {
    onMount: (root) => {
      root.querySelector("#form-close").addEventListener("click", closeModal);
      root.querySelector("#transfer-return-form").addEventListener("submit", async (e) => {
        e.preventDefault();
        const data = Object.fromEntries(new FormData(e.target).entries());
        try {
          await api.post(`/transfers/${transfer.id}/return`, {
            state_after: Number(data.state_after),
            comment: data.comment || null,
          });
          toast("Retour enregistré", "success");
          closeModal();
          onDone();
        } catch (err) {
          toast(err instanceof ApiError ? err.message : "Erreur", "error");
        }
      });
    },
  });
}
