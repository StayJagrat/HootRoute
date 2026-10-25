import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

// The FastAPI gateway listens on 8000. Proxying it through Vite means
// one HTTPS tunnel (Cloudflare / ngrok) serves both the app and the realtime room,
// so a judge's phone that scans the QR code reaches both.
export default defineConfig({
  envDir: '..',            // one .env at the repo root; Vite only exposes VITE_* values to the browser
  plugins: [
    react(),
    VitePWA({
      // The old service worker kept serving cached builds of the previous UI. This one removes itself and its caches.
      selfDestroying: true,
      registerType: 'autoUpdate',
      includeAssets: ['mascots/*.svg', 'data/*.json', 'icons/*.png'],
      manifest: {
        name: 'HootRoute',
        short_name: 'HootRoute',
        description: 'Agentic navigation for the journey after dark.',
        theme_color: '#07090D',
        background_color: '#07090D',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/icon-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,json,woff2}'],
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
        navigateFallbackDenylist: [/^\/ws/],
        runtimeCaching: [
          {
            urlPattern: /\/tiles\/.*\.pmtiles$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'basemap-tiles',
              rangeRequests: true,
              cacheableResponse: { statuses: [0, 200, 206] },
            },
          },
          {
            urlPattern: /\/fonts\/.*\.pbf$/,
            handler: 'CacheFirst',
            options: {
              cacheName: 'map-fonts',
              cacheableResponse: { statuses: [0, 200] },
            },
          },
        ],
      },
    }),
  ],
  server: {
    host: true,
    proxy: {
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
      '/api': { target: 'http://127.0.0.1:8000' },
    },
  },
  preview: {
    proxy: {
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
      '/api': { target: 'http://127.0.0.1:8000' },
    },
  },
});
