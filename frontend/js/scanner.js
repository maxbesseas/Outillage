import { openModal, closeModal } from "./ui.js";
import { icon } from "./icons.js";

export function openScanner(onResult) {
  const supported = "BarcodeDetector" in window;

  const html = `
    <div class="modal-header">
      <div class="card-title">Scanner un code</div>
      <button class="btn btn-ghost btn-sm" id="scanner-close">Fermer</button>
    </div>
    ${supported ? '<video id="scanner-video" playsinline muted style="width:100%;border-radius:7px;background:#000;"></video>' : ""}
    <form id="scanner-manual-form" class="form-grid" style="margin-top:1rem;">
      <div class="field">
        <label>Saisie manuelle du code</label>
        <input type="text" id="scanner-manual-input" autocomplete="off" placeholder="Code de l'outil"/>
      </div>
      <button type="submit" class="btn btn-primary">${icon("check", { size: 16 })} Valider</button>
    </form>
  `;

  let stream = null;
  let rafId = null;
  let stopped = false;

  function stopStream() {
    stopped = true;
    if (rafId) cancelAnimationFrame(rafId);
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
  }

  const backdrop = openModal(html, {
    onMount: (root) => {
      root.querySelector("#scanner-close").addEventListener("click", () => {
        stopStream();
        closeModal();
      });

      const manualForm = root.querySelector("#scanner-manual-form");
      manualForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const value = root.querySelector("#scanner-manual-input").value.trim();
        if (value) {
          stopStream();
          closeModal();
          onResult(value);
        }
      });

      if (supported) {
        const video = root.querySelector("#scanner-video");
        const detector = new window.BarcodeDetector({
          formats: ["code_39", "code_128", "qr_code", "ean_13"],
        });

        navigator.mediaDevices
          .getUserMedia({ video: { facingMode: "environment" } })
          .then((s) => {
            if (stopped) {
              s.getTracks().forEach((t) => t.stop());
              return;
            }
            stream = s;
            video.srcObject = s;
            video.play();

            const detectLoop = async () => {
              if (stopped) return;
              try {
                const codes = await detector.detect(video);
                if (codes.length > 0) {
                  const value = codes[0].rawValue;
                  stopStream();
                  closeModal();
                  onResult(value);
                  return;
                }
              } catch {
                // ignore detection errors, keep trying
              }
              rafId = requestAnimationFrame(detectLoop);
            };
            rafId = requestAnimationFrame(detectLoop);
          })
          .catch(() => {
            // camera unavailable, manual entry remains available
          });
      }
    },
  });

  const observer = new MutationObserver(() => {
    if (!document.body.contains(backdrop)) {
      stopStream();
      observer.disconnect();
    }
  });
  observer.observe(document.body, { childList: true });
}
