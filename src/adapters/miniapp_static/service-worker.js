// Минимальный service worker — нужен только для критериев "установки"
// как полноценного PWA (standalone-режим) в части браузеров, никакого
// офлайн-кэша/стратегии сейчас сознательно нет (см. SPEC.md) — просто
// passthrough на сеть, ничего не перехватывает и не ломает.
self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(self.clients.claim());
});
