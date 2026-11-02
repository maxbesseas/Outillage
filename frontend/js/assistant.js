import { api, ApiError } from "./api.js";
import { escapeHtml, toast } from "./ui.js";

const WELCOME =
  "Bonjour ! Je peux vous expliquer toutes les fonctionnalités de l'application : réservations, prêts, inventaire, EPI, droits par rôle... Posez votre question.";

const SUGGESTIONS = [
  "Comment réserver un outil ?",
  "Comment fonctionne un transfert entre collègues ?",
  "Que peut faire mon rôle ?",
  "Comment contrôler un outil à l'inventaire ?",
];

let history = [];
let busy = false;

function renderText(text) {
  return escapeHtml(text)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\n/g, "<br>");
}

function bubble(role, text, extra = "") {
  return `<div class="chat-msg chat-${role}">${renderText(text)}${extra}</div>`;
}

function proposalCard(p) {
  return `<div class="chat-proposal" data-proposal="${p.id}">
    <div class="chat-proposal-title">Action proposée</div>
    <div>${escapeHtml(p.summary)}</div>
    <div class="card-actions"><button class="btn btn-sm btn-primary" data-confirm="${p.id}">Confirmer</button><button class="btn btn-sm" data-decline="${p.id}">Refuser</button></div>
  </div>`;
}

function feedbackRow(messageId) {
  return `<div class="chat-feedback" data-fb="${messageId}"><span>Cette réponse était-elle utile ?</span>
    <button class="btn btn-sm btn-ghost" data-rate="up" aria-label="Utile">Oui</button><button class="btn btn-sm btn-ghost" data-rate="down" aria-label="Pas utile">Non</button></div>`;
}

function scrollDown(list) {
  list.scrollTop = list.scrollHeight;
}

async function send(text, list, input) {
  const question = text.trim();
  if (!question || busy) return;
  busy = true;
  input.value = "";

  history.push({ role: "user", content: question });
  list.insertAdjacentHTML("beforeend", bubble("user", question));
  list.insertAdjacentHTML("beforeend", `<div class="chat-msg chat-assistant chat-typing" id="chat-typing">…</div>`);
  scrollDown(list);

  try {
    const res = await api.post("/assistant/chat", { messages: history });
    history.push({ role: "assistant", content: res.reply });
    document.getElementById("chat-typing")?.remove();
    const extra = (res.proposals || []).map(proposalCard).join("") + (res.message_id ? feedbackRow(res.message_id) : "");
    list.insertAdjacentHTML("beforeend", bubble("assistant", res.reply, extra));
  } catch (err) {
    history.pop();
    document.getElementById("chat-typing")?.remove();
    const limited = err instanceof ApiError && err.status === 429;
    list.insertAdjacentHTML("beforeend", bubble("assistant", limited ? err.message : "Désolé, une erreur est survenue. Réessayez."));
  } finally {
    busy = false;
    scrollDown(list);
  }
}

function buildPanel() {
  const panel = document.createElement("div");
  panel.id = "assistant-panel";
  panel.className = "assistant-panel hidden";
  panel.innerHTML = `
    <div class="assistant-head">
      <div><strong>Assistant Fauché</strong><div class="card-sub" id="assistant-mode"></div></div>
      <button class="btn btn-ghost btn-sm" id="assistant-close" aria-label="Fermer">✕</button>
    </div>
    <div class="assistant-list" id="assistant-list">
      ${bubble("assistant", WELCOME)}
      <div class="assistant-suggestions">
        ${SUGGESTIONS.map((s) => `<button class="btn btn-sm" data-q="${escapeHtml(s)}">${escapeHtml(s)}</button>`).join("")}
      </div>
    </div>
    <form class="assistant-form" id="assistant-form">
      <input type="text" id="assistant-input" placeholder="Votre question…" autocomplete="off" maxlength="2000"/>
      <button type="submit" class="btn btn-primary btn-sm">Envoyer</button>
    </form>
  `;
  document.body.appendChild(panel);

  const list = panel.querySelector("#assistant-list");
  const input = panel.querySelector("#assistant-input");

  panel.querySelector("#assistant-close").addEventListener("click", () => panel.classList.add("hidden"));
  panel.querySelector("#assistant-form").addEventListener("submit", (e) => {
    e.preventDefault();
    send(input.value, list, input);
  });
  panel.querySelectorAll("[data-q]").forEach((btn) => {
    btn.addEventListener("click", () => send(btn.dataset.q, list, input));
  });

  list.addEventListener("click", async (e) => {
    const confirmBtn = e.target.closest("[data-confirm]");
    const declineBtn = e.target.closest("[data-decline]");
    const rateBtn = e.target.closest("[data-rate]");
    if (confirmBtn || declineBtn) {
      const id = (confirmBtn || declineBtn).dataset.confirm || declineBtn.dataset.decline;
      const card = list.querySelector(`[data-proposal="${id}"]`);
      try {
        if (confirmBtn) {
          const out = await api.post(`/assistant/actions/${id}/confirm`);
          card.innerHTML = `<div class="chat-proposal-title">Fait</div><div>${escapeHtml(out.message || "Action effectuée")}</div>`;
          if (out.warning) toast(`Attention : ${out.warning}`, "error");
        } else {
          await api.post(`/assistant/actions/${id}/cancel`);
          card.innerHTML = `<div class="chat-proposal-title">Refusé</div><div>Aucune modification n'a été faite.</div>`;
        }
      } catch (err) {
        card.querySelectorAll("button").forEach((b) => (b.disabled = true));
        toast(err instanceof ApiError ? err.message : "Erreur", "error");
      }
    } else if (rateBtn) {
      const row = rateBtn.closest("[data-fb]");
      try {
        await api.post("/assistant/feedback", { message_id: Number(row.dataset.fb), rating: rateBtn.dataset.rate });
        row.innerHTML = "<span>Merci pour votre retour.</span>";
      } catch {
        row.remove();
      }
    }
  });

  api.get("/assistant/status").then((st) => {
    const badge = panel.querySelector("#assistant-mode");
    if (badge) badge.textContent = st.ai_enabled ? "IA activée : données de l'application et actions à confirmer" : "Mode documentation (IA non configurée)";
  }).catch(() => {});
}

export function initAssistant() {
  if (document.getElementById("assistant-toggle")) return;

  const toggle = document.createElement("button");
  toggle.id = "assistant-toggle";
  toggle.className = "assistant-toggle";
  toggle.setAttribute("aria-label", "Ouvrir l'assistant");
  toggle.textContent = "?";
  document.body.appendChild(toggle);

  buildPanel();

  toggle.addEventListener("click", () => {
    const panel = document.getElementById("assistant-panel");
    panel.classList.toggle("hidden");
    if (!panel.classList.contains("hidden")) panel.querySelector("#assistant-input").focus();
  });
}

export function destroyAssistant() {
  document.getElementById("assistant-toggle")?.remove();
  document.getElementById("assistant-panel")?.remove();
  history = [];
}
