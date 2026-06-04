import { execSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import VueRouter from 'vue-router/vite'
import { defineConfig, loadEnv } from 'vite'

function readBackendAppDomain(): string {
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
  return execSync('git rev-parse HEAD', {
    cwd: path.resolve(__dirname, '..'),
  })
    .toString()
    .trim()
}

const TITLES: Record<string, string> = {
  '/login': 'Login - DocketWorks',
  '/session-check': 'Connection Check - DocketWorks',
  '/kanban': 'Kanban Board - DocketWorks',
  '/schedule': 'Workshop Schedule - DocketWorks',
  '/jobs/create': 'Create Job - DocketWorks',
  '/jobs/:id': 'Job - DocketWorks',
  '/jobs/:id/workshop': 'Job (Workshop) - DocketWorks',
  '/quoting/chat': 'Interactive Quote Chat - DocketWorks',
  '/timesheets/entry': 'Timesheet Entry - DocketWorks',
  '/timesheets/my-time': 'My Time - Workshop Timesheets',
  '/timesheets/daily': 'Daily Timesheet Overview - DocketWorks',
  '/timesheets/weekly': 'Weekly Timesheet - DocketWorks',
  '/xero': 'Xero Sync - DocketWorks',
  '/crm/clients': 'Clients - DocketWorks',
  '/crm/clients/:id': 'Client Details - DocketWorks',
  '/crm/calls': 'Calls - DocketWorks',
  '/purchasing/po': 'Purchase Orders - DocketWorks',
  '/purchasing/po/create': 'Create Purchase Order - DocketWorks',
  '/purchasing/po/create-from-quote': 'Create PO from Quote - DocketWorks',
  '/purchasing/po/:id': 'Purchase Order - DocketWorks',
  '/purchasing/stock': 'Stock - DocketWorks',
  '/purchasing/mappings': 'Product Mappings - DocketWorks',
  '/purchasing/pricing': 'Supplier Pricing - DocketWorks',
  '/reports/kpi': 'KPI Reports - DocketWorks',
  '/reports/job-aging': 'Job Aging Report - DocketWorks',
  '/reports/staff-performance': 'Staff Performance Report - DocketWorks',
  '/reports/sales-forecast': 'Sales Forecast Report - DocketWorks',
  '/reports/sales-pipeline': 'Sales Pipeline Report - DocketWorks',
  '/reports/profit-and-loss': 'Profit & Loss Report - DocketWorks',
  '/reports/job-movement': 'Job Movement Report - DocketWorks',
  '/reports/data-quality/archived-jobs': 'Archived Jobs Validation - DocketWorks',
  '/reports/job-profitability': 'Job Profitability Report - DocketWorks',
  '/reports/rdti-spend': 'RDTI Spend Report - DocketWorks',
  '/reports/wip': 'WIP Report - DocketWorks',
  '/reports/payroll-reconciliation': 'Payroll Reconciliation - DocketWorks',
}

const WORKSHOP_ALLOWED = [
  '/login',
  '/session-check',
  '/kanban',
  '/jobs/:id',
  '/jobs/:id/workshop',
  '/timesheets/my-time',
]

const SUPERUSER_REQUIRED = [
  '/timesheets/entry',
  '/timesheets/daily',
  '/timesheets/weekly',
  '/crm/calls',
  '/xero',
]

const ALLOW_SCROLL = [
  '/timesheets/my-time',
  '/timesheets/daily',
  '/timesheets/weekly',
  '/reports/staff-performance',
  '/reports/sales-pipeline',
  '/reports/job-profitability',
  '/reports/rdti-spend',
]

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const appDomain = readBackendAppDomain()

  const allowedHosts = ['localhost', appDomain]

  // Check if we're running through localtunnel
  const tunnelHost = env.DEV_TUNNEL_HOST || ''

  return {
    plugins: [
      VueRouter({
        dts: 'src/typed-router.d.ts',
        extendRoute(route) {
          const p = route.path

          if (TITLES[p]) {
            route.addToMeta({ title: TITLES[p] })
          }

          if (p === '/login') {
            route.addToMeta({ requiresGuest: true })
          }

          if (p !== '/login' && p !== '/session-check' && !p.startsWith('/accounts')) {
            route.addToMeta({ requiresAuth: true })
          }

          if (WORKSHOP_ALLOWED.includes(p)) {
            route.addToMeta({ allowWorkshopStaff: true })
          }

          if (SUPERUSER_REQUIRED.includes(p)) {
            route.addToMeta({ requiresSuperUser: true })
          }

          if (ALLOW_SCROLL.includes(p)) {
            route.addToMeta({ allowScroll: true })
          }
        },
      }),
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
