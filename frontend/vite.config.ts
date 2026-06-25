import { execSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import VueRouter from 'vue-router/vite'
import { defineConfig, loadEnv } from 'vite'
import { routerAutoOptions } from './router-auto-options'

function readBackendAppDomain(): string {
  if (process.env.NODE_ENV === 'production') {
    return ''
  }

  const backendEnvPath = path.resolve(__dirname, '..', '.env')
  if (!fs.existsSync(backendEnvPath)) {
    throw new Error(`Backend .env not found at ${backendEnvPath}`)
  }
  const content = fs.readFileSync(backendEnvPath, 'utf8')
  const match = content.match(/^APP_DOMAIN=(.+)$/m)
  if (!match) {
    throw new Error('APP_DOMAIN not set in backend .env')
  }
  return match[1].trim().replace(/^["']|["']$/g, '')
}

function readBuildId(): string {
  const envBuildId = process.env.DOCKETWORKS_BUILD_SHA?.trim()
  if (envBuildId) return envBuildId

  const releaseShaPath = path.resolve(__dirname, '..', '.release-sha')
  if (fs.existsSync(releaseShaPath)) {
    return fs.readFileSync(releaseShaPath, 'utf8').trim()
  }

  return execSync('git rev-parse HEAD', {
    cwd: path.resolve(__dirname, '..'),
  })
    .toString()
    .trim()
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const appDomain = readBackendAppDomain()

  const allowedHosts = appDomain ? ['localhost', appDomain] : ['localhost']

  // Check if we're running through localtunnel
  const tunnelHost = env.DEV_TUNNEL_HOST || ''

  return {
    plugins: [
      VueRouter(routerAutoOptions),
      vue(),
      tailwindcss(),
      {
        name: 'inject-build-id',
        transformIndexHtml: {
          order: 'pre',
          handler: () => [
            {
              tag: 'meta',
              attrs: { name: 'build-id', content: readBuildId() },
              injectTo: 'head',
            },
          ],
        },
      },
    ],
    resolve: {
      dedupe: ['vue'],
      alias: {
        '@': `${path.resolve(__dirname, './src')}`,
        vue: 'vue/dist/vue.esm-bundler.js',
      },
    },
    server: {
      host: '0.0.0.0',
      allowedHosts,
      // Special config for localtunnel compatibility
      ...(tunnelHost
        ? {
            hmr: false,
            // Force HTTP/1.1 to avoid HTTP/2 streaming issues
            cors: true,
            headers: {
              Connection: 'close',
            },
          }
        : {}),
      port: 5173,
      strictPort: true,
      proxy: {
        '/api': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
        '/media': {
          target: 'http://localhost:8000',
          changeOrigin: true,
        },
        // VitePress training manual dev server (npm run manual:dev). In prod
        // nginx serves /manual/ from dist-manual/; in dev we proxy to the
        // VitePress dev server so the navbar "App Training" link works and
        // manual content hot-reloads. ws:true keeps VitePress HMR alive.
        '/manual': {
          target: 'http://localhost:5174',
          changeOrigin: true,
          ws: true,
        },
      },
    },
  }
})
