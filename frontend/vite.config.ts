import { tanstackRouter } from '@tanstack/router-plugin/vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vitest/config'
import { fileURLToPath, URL } from 'node:url'
import fs from 'node:fs'
import path from 'node:path'

// Overridable so dev/E2E can point at a non-default backend port (v1 often
// occupies :8000 on the same machine during the rewrite).
const backendURL = process.env.BACKEND_URL ?? 'http://localhost:8000'
const backendProxy = {
  '/api': backendURL,
  '/media': backendURL,
}

// APP_DOMAIN (the ngrok domain) lives in the backend .env, which VS Code tasks
// don't load, so it is read from the file directly. Absent only in CI /
// prod-artifact builds where the frontend is built without the backend .env
// alongside. allowedHosts is server-side config, never baked into the bundle.
function readBackendAppDomain(): string {
  const backendEnvPath = path.resolve(__dirname, '..', '.env')
  if (!fs.existsSync(backendEnvPath)) {
    return ''
  }
  const content = fs.readFileSync(backendEnvPath, 'utf8')
  const match = content.match(/^APP_DOMAIN=(.+)$/m)
  if (!match) {
    throw new Error('APP_DOMAIN not set in backend .env')
  }
  return match[1].trim().replace(/^["']|["']$/g, '')
}

const appDomain = readBackendAppDomain()
const allowedHosts = appDomain ? ['localhost', appDomain] : ['localhost']

export default defineConfig({
  plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    proxy: backendProxy,
    allowedHosts,
  },
  // `vite preview` serves the production build (E2E harness) — it does NOT
  // inherit `server.proxy` or `server.allowedHosts`, so both are mirrored here
  // (v1 did the same).
  preview: {
    port: 4173,
    strictPort: true,
    proxy: backendProxy,
    allowedHosts,
  },
  test: {
    projects: [
      {
        extends: true,
        test: {
          name: 'node',
          environment: 'node',
          include: ['src/**/*.test.ts', 'tests/**/*.test.ts'],
        },
      },
      {
        extends: true,
        test: {
          name: 'dom',
          environment: 'jsdom',
          include: ['src/**/*.test.tsx'],
          setupFiles: ['./src/test/setup.ts'],
        },
      },
    ],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        'src/api/generated/**',
        'src/routeTree.gen.ts',
        'src/test/**',
        'src/**/*.test.{ts,tsx}',
        'src/**/*.d.ts',
      ],
      reporter: ['text', 'text-summary', 'html', 'json-summary'],
    },
  },
})
