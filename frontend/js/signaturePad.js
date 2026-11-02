import { openModal, closeModal, toast } from "./ui.js";

/** Signature tactile : renvoie {w, h, strokes: [[[x, y], ...], ...]} (traits vectoriels). */
export function openSignaturePad(title, onSave, defaultName = "") {
  openModal(
    `
    <div class="modal-header">
      <div class="card-title">${title}</div>
      <button class="btn btn-ghost btn-sm" id="sig-close">Fermer</button>
    </div>
    <div class="form-grid">
      <div class="field">
        <label>Nom du signataire</label>
        <input id="sig-name" value="${(defaultName || "").replace(/"/g, "&quot;")}" maxlength="120"/>
      </div>
      <canvas id="sig-canvas" class="sig-canvas" width="600" height="220" aria-label="Zone de signature"></canvas>
      <div class="card-actions">
        <button class="btn btn-sm" id="sig-clear">Effacer</button>
        <button class="btn btn-primary" id="sig-save">Enregistrer la signature</button>
      </div>
    </div>`,
    {
      onMount: (root) => {
        const canvas = root.querySelector("#sig-canvas");
        const ctx = canvas.getContext("2d");
        ctx.lineWidth = 2.5;
        ctx.lineCap = "round";
        ctx.lineJoin = "round";
        ctx.strokeStyle = "#111";

        let strokes = [];
        let current = null;

        const point = (e) => {
          const rect = canvas.getBoundingClientRect();
          return [
            Math.round(((e.clientX - rect.left) / rect.width) * canvas.width * 10) / 10,
            Math.round(((e.clientY - rect.top) / rect.height) * canvas.height * 10) / 10,
          ];
        };

        canvas.addEventListener("pointerdown", (e) => {
          canvas.setPointerCapture(e.pointerId);
          current = [point(e)];
          strokes.push(current);
          ctx.beginPath();
          ctx.moveTo(...current[0]);
          e.preventDefault();
        });
        canvas.addEventListener("pointermove", (e) => {
          if (!current) return;
          const p = point(e);
          current.push(p);
          ctx.lineTo(...p);
          ctx.stroke();
          e.preventDefault();
        });
        const end = () => {
          if (current && current.length === 1) {
            ctx.lineTo(current[0][0] + 0.1, current[0][1]);
            ctx.stroke();
          }
          current = null;
        };
        canvas.addEventListener("pointerup", end);
        canvas.addEventListener("pointercancel", end);

        root.querySelector("#sig-clear").addEventListener("click", () => {
          strokes = [];
          ctx.clearRect(0, 0, canvas.width, canvas.height);
        });
        root.querySelector("#sig-close").addEventListener("click", closeModal);
        root.querySelector("#sig-save").addEventListener("click", () => {
          if (!strokes.length) {
            toast("Signez dans le cadre avant d'enregistrer", "error");
            return;
          }
          const name = root.querySelector("#sig-name").value.trim();
          closeModal();
          onSave({ w: canvas.width, h: canvas.height, strokes }, name || null);
        });
      },
    }
  );
}
