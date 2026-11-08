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

// TM05-160: inside the dev container (.devcontainer/ sets CAMPSITE_DEVCONTAINER=1) the page
// is opened through a forwarded port: localhost in VS Code, or
// https://<codespace>-5173.app.github.dev in a Codespace. Vite listens on all of the
// container's interfaces, accepts the Codespaces host name, and proxies /api to Django, so
// the API is same-origin there too and needs no CORS. An empty VITE_API_BASE_URL makes the
// app call /api on its own origin; set it explicitly to override.
const devcontainer = process.env.CAMPSITE_DEVCONTAINER === '1'
if (devcontainer && process.env.VITE_API_BASE_URL === undefined) {
  process.env.VITE_API_BASE_URL = ''
}
const codespacesDomain = process.env.GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN || 'app.github.dev'

const apiProxy = { '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true } }

export default defineConfig({
  plugins: [react(), ...(phone ? [basicSsl()] : [])],
  optimizeDeps: {
    exclude: ['maplibre-gl'],
  },
  server: phone
    ? { host: true, proxy: apiProxy }
    : devcontainer
      ? { host: true, port: 5173, strictPort: true, allowedHosts: [`.${codespacesDomain}`], proxy: apiProxy }
      : undefined,
})
