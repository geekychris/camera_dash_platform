// camera_dash service worker.
//
// Two jobs:
//   1) Receive Web Push messages from the backend (POST /api/notifications/send)
//      and surface them as native OS notifications. Payload is JSON shaped
//      like { title, body, tag, url, icon }.
//   2) Provide an offline fallback for the SPA shell so the dashboard at
//      least loads (and shows last-cached tiles) when the LAN is unreachable.
//
// Kept dependency-free — no Workbox, no Vite-PWA — so it ships as a static
// asset from the same Vite dev server / nginx the rest of the app uses.

const CACHE = "camera_dash-v1";
const SHELL = ["/", "/dashboard", "/manifest.webmanifest"];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()),
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    Promise.all([
      // Drop any stale older-version caches.
      caches.keys().then((keys) =>
        Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))),
      ),
      self.clients.claim(),
    ]),
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  // Only handle SPA navigations from the cache; let API/proxy/etc. pass through.
  if (req.mode !== "navigate") return;
  event.respondWith(
    fetch(req).catch(() =>
      caches.match(req).then((m) => m || caches.match("/")) ,
    ),
  );
});

self.addEventListener("push", (event) => {
  if (!event.data) return;
  let payload;
  try {
    payload = event.data.json();
  } catch {
    payload = { title: "camera_dash", body: event.data.text() };
  }
  const title = payload.title || "camera_dash";
  const options = {
    body: payload.body || "",
    tag: payload.tag || "default", // same tag → newer replaces older
    icon: payload.icon || "/icon-192.png",
    data: { url: payload.url || "/dashboard" },
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = (event.notification.data && event.notification.data.url) || "/dashboard";
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      for (const w of windows) {
        if (w.url.endsWith(url) && "focus" in w) return w.focus();
      }
      if (self.clients.openWindow) return self.clients.openWindow(url);
    }),
  );
});
