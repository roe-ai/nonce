// nonce's service worker: shows Web Push alerts and opens the dashboard when one is tapped.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    (async () => {
      await self.registration.showNotification(data.title || "nonce", {
        body: data.body || "",
        icon: "/icon-192.png",
        badge: "/badge-96.png",
        tag: data.tag || undefined,
        data: { url: data.url || "/" },
      });
      // Open dashboards pick up the new request without waiting for their next refresh.
      for (const client of await self.clients.matchAll({ type: "window" })) client.postMessage({ type: "nonce:refresh" });
    })(),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/", self.location.origin);
  // Only ever open this dashboard.
  const url = target.origin === self.location.origin ? target.href : self.location.origin + "/";
  event.waitUntil(
    (async () => {
      for (const client of await self.clients.matchAll({ type: "window", includeUncontrolled: true })) {
        if (new URL(client.url).origin === self.location.origin) {
          await client.focus();
          if ("navigate" in client) await client.navigate(url);
          return;
        }
      }
      await self.clients.openWindow(url);
    })(),
  );
});
