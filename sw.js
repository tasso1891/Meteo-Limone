const CACHE = 'meteo-limone-v20';
const SHELL = ['./', './index.html', './manifest.json', './icon-192.png', './icon-512.png', './apple-touch-icon.png'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(SHELL)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (u.origin !== location.origin) return; // previsioni: sempre dalla rete
  // app: prima la rete (così gli aggiornamenti arrivano subito), poi la copia salvata
  e.respondWith(
    fetch(e.request.url, {cache: 'no-cache'}).then(r => {
      const c = r.clone(); caches.open(CACHE).then(ca => ca.put(e.request, c));
      return r;
    }).catch(() => caches.match(e.request).then(r => r || caches.match('./index.html')))
  );
});
