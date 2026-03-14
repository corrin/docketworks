import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  const allowedHosts = [
    'localhost',
    ...(env.VITE_ALLOWED_HOSTS ? env.VITE_ALLOWED_HOSTS.split(',').map((host) => host.trim()) : []),
  ]

  // Check if we're running through localtunnel
  const tunnelHost = env.DEV_TUNNEL_HOST || ''

  return {
    plugins: [vue(), tailwindcss()],
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
    },
  }
})
