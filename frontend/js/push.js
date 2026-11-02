import { api } from "./api.js";

export function pushSupported() {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

function urlBase64ToUint8Array(base64) {
  const padding = "=".repeat((4 - (base64.length % 4)) % 4);
  const raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export async function currentSubscription() {
  if (!pushSupported()) return null;
  const registration = await navigator.serviceWorker.ready;
  return registration.pushManager.getSubscription();
}

export async function enablePush() {
  if (!pushSupported()) throw new Error("Les notifications push ne sont pas disponibles sur cet appareil");
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Autorisation de notification refusée");

  const { public_key } = await api.get("/push/public-key");
  const registration = await navigator.serviceWorker.ready;
  const subscription =
    (await registration.pushManager.getSubscription()) ||
    (await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(public_key),
    }));
  const json = subscription.toJSON();
  await api.post("/push/subscribe", { endpoint: json.endpoint, keys: json.keys });
}

export async function disablePush() {
  const subscription = await currentSubscription();
  if (!subscription) return;
  const endpoint = subscription.endpoint;
  await subscription.unsubscribe();
  await api.delete("/push/subscribe", { endpoint });
}
