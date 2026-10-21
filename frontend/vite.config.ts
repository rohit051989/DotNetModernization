/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Component tests (release 6): `npm test`. Files next to what they test, named *.test.tsx.
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.tsx'],
  },
})
