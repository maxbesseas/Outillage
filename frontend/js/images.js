const DEFAULTS = { maxPx: 1600, quality: 0.8 };
let cached = null;

export function setImageSettings(settings) {
  cached = { ...DEFAULTS, ...settings };
}

/** Redimensionne et recompresse une photo côté client (économise le réseau sur le terrain). */
export async function compressImage(file, options = {}) {
  const { maxPx, quality } = { ...(cached || DEFAULTS), ...options };
  if (!file || !file.type || !file.type.startsWith("image/") || file.type === "image/gif") return file;
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, maxPx / Math.max(bitmap.width, bitmap.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close?.();
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, "image/jpeg", quality));
    if (!blob) return file;
    return new File([blob], (file.name || "photo").replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
  } catch {
    return file;
  }
}
