import { useEffect, useState } from "react";

/**
 * Header button that toggles the browser's PushSubscription for this device.
 * Fetches the server's VAPID public key on mount; if VAPID isn't configured,
 * the button shows a tooltip explaining what to set and is disabled.
 *
 * Permission/Subscription state is read on every mount via the service-worker
 * registration so the button reflects the truth even if the user changed
 * permissions in the browser between sessions.
 */
export default function NotifyButton() {
  const [state, setState] = useState<"unsupported" | "off" | "on" | "denied" | "noVapid" | "loading">("loading");
  const [vapid, setVapid] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
      setState("unsupported");
      return;
    }
    (async () => {
      try {
        const r = await fetch("/api/notifications/vapid").then((r) => r.json());
        if (cancelled) return;
        if (!r.publicKey) { setState("noVapid"); return; }
        setVapid(r.publicKey);
        const reg = await navigator.serviceWorker.ready;
        const sub = await reg.pushManager.getSubscription();
        if (cancelled) return;
        if (Notification.permission === "denied") setState("denied");
        else setState(sub ? "on" : "off");
      } catch {
        if (!cancelled) setState("off");
      }
    })();
    return () => { cancelled = true; };
  }, []);

  async function toggle() {
    if (state === "on") {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.getSubscription();
      if (sub) {
        // Server keys subscriptions by hashed endpoint, so derive the same id.
        const id = await shaTrunc(sub.endpoint);
        await sub.unsubscribe();
        await fetch(`/api/notifications/subscribe/${id}`, { method: "DELETE" });
      }
      setState("off");
      return;
    }
    if (!vapid) return;
    const perm = await Notification.requestPermission();
    if (perm !== "granted") { setState("denied"); return; }
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapid),
    });
    await fetch("/api/notifications/subscribe", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ subscription: sub.toJSON(), kinds: [] }),
    });
    setState("on");
  }

  const label = {
    loading: "…",
    unsupported: "no push",
    noVapid: "no VAPID",
    denied: "blocked",
    off: "alerts off",
    on: "alerts on",
  }[state];
  const cls = state === "on"
    ? "border-emerald-700 text-emerald-300 hover:bg-emerald-900/40"
    : "border-slate-700 text-slate-300 hover:bg-slate-800";
  const disabled = state === "loading" || state === "unsupported" || state === "denied" || state === "noVapid";
  const title = state === "noVapid"
    ? "Set CAMERA_DASH_VAPID_PUBLIC_KEY + CAMERA_DASH_VAPID_PRIVATE_KEY to enable push"
    : state === "denied"
      ? "Browser has blocked notifications — change it in site permissions"
      : state === "on"
        ? "Disable push notifications on this device"
        : "Enable push notifications on this device";
  return (
    <button
      onClick={toggle}
      disabled={disabled}
      title={title}
      className={`rounded border px-2 py-0.5 disabled:opacity-50 ${cls}`}
    >
      🔔 {label}
    </button>
  );
}

// Same hash as backend's _short_id — keeps DELETE keyed correctly.
async function shaTrunc(s: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-1", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(buf)).map((b) => b.toString(16).padStart(2, "0")).join("").slice(0, 12);
}

function urlBase64ToUint8Array(b64: string): Uint8Array {
  const padding = "=".repeat((4 - (b64.length % 4)) % 4);
  const base64 = (b64 + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  const out = new Uint8Array(raw.length);
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}
