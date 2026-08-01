import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'
import { fileURLToPath, URL } from 'node:url'

// Overridable so dev/E2E can point at a non-default backend port (v1 often
// occupies :8000 on the same machine during the rewrite).
const backendURL = process.env.BACKEND_URL ?? 'http://localhost:8000'
const backendProxy = {
  '/api': backendURL,
  '/media': backendURL,
}

export default defineConfig({
  plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: backendProxy,
  },
  // `vite preview` serves the production build (E2E harness) — it does NOT
  // inherit `server.proxy`, so the backend proxy is mirrored here (v1 did the same).
  preview: {
    port: 4173,
    strictPort: true,
    proxy: backendProxy,
  },
  test: {
    include: ['src/**/*.test.ts'], // Playwright specs live in tests/e2e/, not vitest
  },
})
