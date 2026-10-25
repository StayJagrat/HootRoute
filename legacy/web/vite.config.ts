import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['icon.svg', 'icon-180.png'],
      manifest: {
        name: 'Streetwise',
        short_name: 'Streetwise',
        description: 'Smart walking navigation: what is open, lit and reachable when you pass.',
        theme_color: '#070b12',
        background_color: '#070b12',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
          { src: 'icon.svg', sizes: 'any', type: 'image/svg+xml' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        maximumFileSizeToCacheInBytes: 6 * 1024 * 1024,
        runtimeCaching: [
          { urlPattern: /\/api\/(meta|landmarks|places|heat)/, handler: 'NetworkFirst', options: { cacheName: 'api-static', networkTimeoutSeconds: 3 } },
          { urlPattern: /\/tiles\/.*\.pmtiles$/, handler: 'CacheFirst', options: { cacheName: 'basemap-tiles', rangeRequests: true, cacheableResponse: { statuses: [0, 200, 206] } } },
          { urlPattern: /\/fonts\/.*\.pbf$/, handler: 'CacheFirst', options: { cacheName: 'map-fonts' } },
        ],
      },
    }),
  ],
  server: { host: true, port: 5173, proxy: { '/api': { target: 'http://127.0.0.1:8000', configure: (p) => { p.on('error', () => {}) } }, '/ws': { target: 'ws://127.0.0.1:8000', ws: true, configure: (p) => { p.on('error', () => {}) } } } },
})
