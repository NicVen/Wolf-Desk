/* STAALCALIBUR app service worker — caches the shell for instant/offline open;
   license + data calls (/appdata, /verify) always hit the network. */
var SHELL = "sc-shell-v5";
var URLS = ["/", "/scapp.webmanifest", "/icon-192.png", "/icon-512.png"];

self.addEventListener("install", function (e) {
  e.waitUntil(caches.open(SHELL).then(function (c) { return c.addAll(URLS).catch(function(){}); })
    .then(function () { return self.skipWaiting(); }));
});
// "Update now" in the app asks a waiting SW to take over immediately.
self.addEventListener("message", function (e) {
  if (e.data && e.data.type === "SKIP_WAITING") self.skipWaiting();
});
self.addEventListener("activate", function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== SHELL; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});
self.addEventListener("fetch", function (e) {
  var u = new URL(e.request.url);
  if (/^\/(appdata|verify|appversion)\b/.test(u.pathname)) return;   // never cache license/data/version
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
