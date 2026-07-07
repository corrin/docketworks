import path from 'node:path'
import vue from '@vitejs/plugin-vue'
import VueRouter from 'vue-router/vite'
import { defineConfig } from 'vitest/config'
import { routerAutoOptions } from './router-auto-options'

export default defineConfig({
  plugins: [
    VueRouter({
      ...routerAutoOptions,
      dts: false,
    }),
    vue(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    include: ['src/**/*.{test,spec}.{js,ts}'],
    exclude: ['**/node_modules/**', '**/dist/**', 'tests/**'],
  },
})
