const CACHE_NAME = 'zapbudget-v3';
const ASSETS_TO_CACHE = [
  '/',
  '/index.html',
  '/app/templates/site.html',
  '/app/templates/view.html',
  '/app/templates/img/favicon (3).png',
  'https://cdn.tailwindcss.com',
  'https://unpkg.com/lucide@latest'
];

// Instalação do Service Worker e cache de arquivos estáticos
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(ASSETS_TO_CACHE);
    })
  );
});

// Estratégia de busca: Tenta a rede primeiro, se falhar, usa o cache
self.addEventListener('fetch', (event) => {
  event.respondWith(
    fetch(event.request).catch(() => {
      return caches.match(event.request);
    })
  );
});
