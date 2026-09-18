/* WOLF Desk PWA service worker — caches the app shell so the page opens
   offline / instantly; data calls (/data, /news, /refresh) always hit the
   network and are never cached. */
var SHELL = "wolf-shell-v2";
var SHELL_URLS = ["/", "/manifest.json", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", function (e) {
  e.waitUntil(
    caches.open(SHELL).then(function (c) { return c.addAll(SHELL_URLS).catch(function(){}); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (e) {
  e.waitUntil(
    caches.keys().then(function (keys) {
      return Promise.all(keys.filter(function (k) { return k !== SHELL; })
        .map(function (k) { return caches.delete(k); }));
    }).then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (e) {
  var url = new URL(e.request.url);
  // never cache API/data responses — always fresh
  if (/^\/(data|news|refresh|rates|calendar|fx|health)\b/.test(url.pathname)) {
    return; // default network handling
  }
  // shell: network-first, fall back to cache when offline
  e.respondWith(
    fetch(e.request).then(function (res) {
      if (res && res.ok && e.request.method === "GET") {
        var copy = res.clone();
        caches.open(SHELL).then(function (c) { c.put(e.request, copy).catch(function(){}); });
      }
      return res;
    }).catch(function () { return caches.match(e.request).then(function (m) { return m || caches.match("/"); }); })
  );
});
