/// <reference types="vitest/config" />
import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // The backend's address, from frontend/.env (scripts/bootstrap.ps1 writes it). The page calls its own origin, and
  // the dev server passes /api on, so the backend's session cookie is the page's own (app.auth).
  const backend = loadEnv(mode, process.cwd(), '').VITE_API_BASE_URL || 'http://127.0.0.1:8001'
  return {
    plugins: [react()],
    server: {
      proxy: { '/api': { target: backend, changeOrigin: false } },
    },
    // Component tests (release 6): `npm test`. Files next to what they test, named *.test.tsx.
    test: {
      environment: 'jsdom',
      include: ['src/**/*.test.tsx'],
    },
  }
})
