// Bump CACHE_NAME whenever a precached file below changes shape (renamed/added).
// Section pages are not listed: they are cached as they are visited, so adding a
// section never needs a change here.
const CACHE_NAME = 'applied-ai-hub-v2';
const BASE = '/applied-ai-hub/';
const STATIC_ASSETS = [
  BASE,
  BASE + 'index.html',
  BASE + 'player.html',
  BASE + 'assets/hub.css',
  BASE + 'assets/hub.js',
  BASE + 'assets/topics.js',
  BASE + 'manifest.json',
  BASE + 'icons/icon-192.png',
  BASE + 'icons/icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// Fetch strategy (same-origin GETs only; thumbnails and YouTube go straight to network):
//   icons / manifest              -> cache first, network fallback (rarely change)
//   pages, assets, data/*.json    -> network first, cache fallback (always fresh, works offline)
self.addEventListener('fetch', e => {
  const url = new URL(e.request.url);
  if (e.request.method !== 'GET' || url.origin !== self.location.origin) return;

  const rarelyChanges = url.pathname.includes('/icons/') || url.pathname.endsWith('manifest.json');
  if (rarelyChanges) {
    e.respondWith(caches.match(e.request).then(cached => cached || fetch(e.request)));
    return;
  }

  e.respondWith(
    fetch(e.request)
      .then(res => {
        if (res.ok) {
          const clone = res.clone();
          caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        }
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
