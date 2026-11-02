import { openModal, closeModal, escapeHtml } from "./ui.js";
import { icon } from "./icons.js";
import { cameraErrorMessage, cameraSupported, openCameraStream } from "./cameraCapture.js";

const NATIVE_FORMATS = ["code_39", "code_128", "qr_code", "ean_13"];
const SCAN_INTERVAL_MS = 150;
let zxingLoading = null;

// Bibliothèque de secours, chargée seulement si le navigateur ne sait pas lire les codes (iPhone, Windows, Firefox).
function loadZxing() {
  if (window.ZXing) return Promise.resolve(window.ZXing);
  if (!zxingLoading) {
    zxingLoading = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/js/vendor/zxing.min.js";
      script.onload = () => resolve(window.ZXing);
      script.onerror = () => {
        zxingLoading = null;
        reject(new Error("zxing"));
      };
      document.head.appendChild(script);
    });
  }
  return zxingLoading;
}

async function nativeDetector() {
  if (!("BarcodeDetector" in window)) return null;
  try {
    const supported = await window.BarcodeDetector.getSupportedFormats();
    if (!NATIVE_FORMATS.every((format) => supported.includes(format))) return null;
    const detector = new window.BarcodeDetector({ formats: NATIVE_FORMATS });
    return async (video) => (await detector.detect(video))[0]?.rawValue || null;
  } catch {
    return null;
  }
}

async function zxingDetector() {
  const ZXing = await loadZxing();
  const hints = new Map();
  hints.set(ZXing.DecodeHintType.POSSIBLE_FORMATS, [ZXing.BarcodeFormat.CODE_39, ZXing.BarcodeFormat.CODE_128, ZXing.BarcodeFormat.QR_CODE, ZXing.BarcodeFormat.EAN_13]);
  hints.set(ZXing.DecodeHintType.TRY_HARDER, true);
  const reader = new ZXing.MultiFormatReader();
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d", { willReadFrequently: true });
  return (video) => {
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    context.drawImage(video, 0, 0);
    try {
      const bitmap = new ZXing.BinaryBitmap(new ZXing.HybridBinarizer(new ZXing.HTMLCanvasElementLuminanceSource(canvas)));
      return reader.decode(bitmap, hints).getText();
    } catch {
      return null; // aucun code sur cette image
    }
  };
}

export function openScanner(onResult) {
  const html = `
    <div class="modal-header">
      <div class="card-title">Scanner un code</div>
      <button class="btn btn-ghost btn-sm" id="scanner-close">Fermer</button>
    </div>
    ${cameraSupported() ? '<video id="scanner-video" class="camera-video" playsinline muted autoplay></video>' : ""}
    <p id="scanner-status" class="camera-message" role="status"></p>
    <form id="scanner-manual-form" class="form-grid" style="margin-top:1rem;">
      <div class="field">
        <label>Saisie manuelle du code</label>
        <input type="text" id="scanner-manual-input" autocomplete="off" placeholder="Code de l'outil"/>
      </div>
      <button type="submit" class="btn btn-primary">${icon("check", { size: 16 })} Valider</button>
    </form>
  `;

  let stream = null;
  let timer = null;
  let stopped = false;

  function stopStream() {
    stopped = true;
    clearTimeout(timer);
    stream?.getTracks().forEach((track) => track.stop());
    stream = null;
  }

  function finish(value) {
    stopStream();
    closeModal();
    onResult(value);
  }

  async function startCamera(root) {
    const status = root.querySelector("#scanner-status");
    const video = root.querySelector("#scanner-video");
    if (!video) {
      status.textContent = "Ce navigateur ne donne pas accès à la caméra. Saisissez le code ci-dessous.";
      return;
    }
    status.textContent = "Démarrage de la caméra…";
    try {
      const opened = await openCameraStream();
      if (stopped) {
        opened.getTracks().forEach((track) => track.stop());
        return;
      }
      stream = opened;
      video.srcObject = opened;
      await video.play();
      status.textContent = "Préparation de la lecture des codes…";
      const detect = (await nativeDetector()) || (await zxingDetector());
      if (stopped) return;
      status.textContent = "Placez le code devant la caméra.";
      const scan = async () => {
        if (stopped) return;
        let value = null;
        try {
          if (video.videoWidth) value = await detect(video);
        } catch {
          // une image illisible n'arrête pas la lecture
        }
        if (value) return finish(value);
        timer = setTimeout(scan, SCAN_INTERVAL_MS);
      };
      scan();
    } catch (err) {
      if (stopped) return;
      console.warn("Caméra :", err?.name, err?.message);
      status.textContent = err?.message === "zxing" ? "La lecture des codes n'a pas pu se charger. Vérifiez la connexion, ou saisissez le code." : `${escapeHtml(cameraErrorMessage(err))} Vous pouvez aussi saisir le code.`;
      video.classList.add("hidden");
    }
  }

  const backdrop = openModal(html, {
    onMount: (root) => {
      root.querySelector("#scanner-close").addEventListener("click", () => {
        stopStream();
        closeModal();
      });

      root.querySelector("#scanner-manual-form").addEventListener("submit", (e) => {
        e.preventDefault();
        const value = root.querySelector("#scanner-manual-input").value.trim();
        if (value) finish(value);
      });

      startCamera(root);
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
