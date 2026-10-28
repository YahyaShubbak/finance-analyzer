import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// In production the backend serves the built app itself (same origin).
// During `npm run dev`, API calls go to the Vite server and are proxied to
// the backend, so the app is same-origin in both cases.
const backend = process.env.FINANCE_BACKEND_URL ?? 'http://127.0.0.1:8420'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: backend, changeOrigin: true },
      '/health': { target: backend, changeOrigin: true },
    },
  },
})
