// frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import basicSsl from '@vitejs/plugin-basic-ssl'

// TM05-103: `make dev-phone` sets PHONE=1 to test on a real phone. Browsers only offer
// geolocation over HTTPS (or localhost), so the dev server then serves HTTPS on the LAN with
// a throwaway self-signed certificate (dev only, never in a build), and proxies /api to
// Django on this machine. The page and the API are then the same origin, so the phone
// needs no CORS and no mixed-content exceptions. docs/setup.md, "Testing on a phone".
const phone = process.env.PHONE === '1'

export default defineConfig({
  plugins: [react(), ...(phone ? [basicSsl()] : [])],
  optimizeDeps: {
    exclude: ['maplibre-gl'],
  },
  server: phone
    ? {
        host: true,
        proxy: { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } },
      }
    : undefined,
})
