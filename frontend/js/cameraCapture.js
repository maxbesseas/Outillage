// Caméra : messages d'erreur clairs, et prise de photo depuis la webcam quand l'appareil n'a pas d'appareil photo intégré au champ de fichier.

export function cameraSupported() {
  return !!navigator.mediaDevices?.getUserMedia;
}

export function cameraErrorMessage(err) {
  if (!window.isSecureContext) return "La caméra n'est disponible que sur une adresse sécurisée (https).";
  switch (err?.name) {
    case "NotAllowedError":
    case "SecurityError":
      return "L'accès à la caméra est refusé. Autorisez-le dans les réglages du navigateur pour ce site, puis réessayez.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "Aucune caméra n'a été trouvée sur cet appareil.";
    case "NotReadableError":
    case "AbortError":
      return "La caméra est déjà utilisée par une autre application. Fermez-la, puis réessayez.";
    default:
      return "La caméra n'a pas pu démarrer. Rechargez la page, puis réessayez.";
  }
}

export function openCameraStream() {
  return navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: "environment" } }, audio: false });
}

function capturePhoto(onFile) {
  const overlay = document.createElement("div");
  overlay.className = "camera-overlay";
  overlay.setAttribute("role", "dialog");
  overlay.setAttribute("aria-modal", "true");
  overlay.setAttribute("aria-label", "Prendre une photo");
  overlay.innerHTML = `
    <video class="camera-video" playsinline muted autoplay></video>
    <p class="camera-message" role="status">Démarrage de la caméra…</p>
    <div class="camera-actions">
      <button type="button" class="btn btn-primary" data-camera-shoot disabled>Prendre la photo</button>
      <button type="button" class="btn" data-camera-cancel>Annuler</button>
    </div>`;
  document.body.appendChild(overlay);

  const video = overlay.querySelector("video");
  const message = overlay.querySelector(".camera-message");
  const shoot = overlay.querySelector("[data-camera-shoot]");
  let stream = null;

  const close = () => {
    stream?.getTracks().forEach((track) => track.stop());
    document.removeEventListener("keydown", onKey, true);
    overlay.remove();
  };
  const onKey = (event) => {
    if (event.key !== "Escape") return;
    event.stopPropagation();
    close();
  };
  document.addEventListener("keydown", onKey, true);
  overlay.querySelector("[data-camera-cancel]").addEventListener("click", close);

  openCameraStream()
    .then(async (opened) => {
      stream = opened;
      if (!overlay.isConnected) return close();
      video.srcObject = opened;
      await video.play();
      message.textContent = "";
      shoot.disabled = false;
      shoot.focus();
    })
    .catch((err) => {
      message.textContent = cameraErrorMessage(err);
    });

  shoot.addEventListener("click", () => {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    canvas.toBlob(
      (blob) => {
        close();
        if (blob) onFile(new File([blob], "photo.jpg", { type: "image/jpeg" }));
      },
      "image/jpeg",
      0.85
    );
  });
}

function wirePhotoInputs() {
  document.querySelectorAll('input[type="file"][capture]:not([data-camera-wired])').forEach((input) => {
    input.dataset.cameraWired = "1";
    const button = document.createElement("button");
    button.type = "button";
    button.className = "btn btn-sm camera-open";
    button.textContent = "Prendre une photo";
    button.addEventListener("click", () => {
      capturePhoto((file) => {
        const transfer = new DataTransfer();
        transfer.items.add(file);
        input.files = transfer.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
        button.textContent = "Photo prise : la refaire";
      });
    });
    input.after(button);
  });
}

/** Sur ordinateur, un champ photo n'ouvre que l'explorateur de fichiers : on y ajoute l'accès à la webcam. */
export function startWebcamPhotos() {
  if (!cameraSupported() || matchMedia("(pointer: coarse)").matches) return;
  let scheduled = false;
  new MutationObserver(() => {
    if (scheduled) return;
    scheduled = true;
    requestAnimationFrame(() => {
      scheduled = false;
      wirePhotoInputs();
    });
  }).observe(document.body, { childList: true, subtree: true });
  wirePhotoInputs();
}
