import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const srcRoot = path.resolve(process.cwd(), 'src')

const allowedTransportImports = new Set([
  'components/job/JobAttachmentsTab.vue',
  'composables/useJobAttachments.ts',
  'composables/useXeroAuth.ts',
  'pages/purchasing/po/create-from-quote.vue',
  'services/admin-company-defaults-service.ts',
  'services/job.service.ts',
  'services/payroll.service.ts',
  'stores/purchaseOrderStore.ts',
  'views/XeroAppSettings.vue',
])

const allowedDirectApiLines = new Map([
  [
    'pages/purchasing/po/create-from-quote.vue',
    [/api\.post\('\/api\/purchasing\/supplier-quotes\/extract\/'/],
  ],
  [
    'services/admin-company-defaults-service.ts',
    [/fetch\('\/api\/company-defaults\/upload-logo\/'/],
  ],
  [
    'services/job.service.ts',
    [
      /axios\.get\(`\/api\/job\/jobs\/\$\{jobId\}\/workshop-pdf\/`/,
      /axios\.get\(`\/api\/job\/jobs\/\$\{jobId\}\/delivery-docket\/`/,
      /axios\.post\(`\/api\/job\/jobs\/\$\{jobId\}\/files\/`/,
    ],
  ],
  [
    'stores/purchaseOrderStore.ts',
    [/axios\.get\(`\/api\/purchasing\/purchase-orders\/\$\{id\}\/pdf\/`/],
  ],
])

const ignoredPathParts = new Set(['api/generated', '__tests__'])

const forbiddenPatterns = [
  {
    label: 'raw fetch to /api',
    regex: /\bfetch\s*\(\s*['"`]\/api\//,
  },
  {
    label: 'api.axios direct API call',
    regex: /\bapi\.axios\.(?:get|post|put|patch|delete)\s*\(\s*['"`]\/api\//,
  },
  {
    label: 'axios direct API call',
    regex: /\baxios\.(?:get|post|put|patch|delete)\s*\(\s*['"`]\/api\//,
  },
  {
    label: 'axios alias direct API call',
    regex: /\b\w+\.(?:get|post|put|patch|delete)\s*\(\s*['"`]\/api\//,
  },
  {
    label: 'frontend axios transport import',
    regex: /from\s+['"](?:@\/|\.\.?\/)+plugins\/axios['"]/,
  },
]

function isAllowedViolation(relativePath, label, line) {
  if (label === 'frontend axios transport import') {
    return allowedTransportImports.has(relativePath)
  }

  const allowedLinePatterns = allowedDirectApiLines.get(relativePath) ?? []
  return allowedLinePatterns.some((pattern) => pattern.test(line))
}

function listSourceFiles(dir) {
  const entries = fs.readdirSync(dir, { withFileTypes: true })
  const files = []

  for (const entry of entries) {
    const absolutePath = path.join(dir, entry.name)
    const relativePath = path.relative(srcRoot, absolutePath).split(path.sep).join('/')

    if ([...ignoredPathParts].some((ignored) => relativePath.includes(ignored))) {
      continue
    }

    if (entry.isDirectory()) {
      files.push(...listSourceFiles(absolutePath))
      continue
    }

    if (/\.(ts|vue)$/.test(entry.name)) {
      files.push(absolutePath)
    }
  }

  return files
}

const violations = []

for (const filePath of listSourceFiles(srcRoot)) {
  const relativePath = path.relative(srcRoot, filePath).split(path.sep).join('/')
  if (relativePath === 'api/client.ts' || relativePath === 'plugins/axios.ts') {
    continue
  }

  const content = fs.readFileSync(filePath, 'utf8')
  const lines = content.split('\n')
  for (const pattern of forbiddenPatterns) {
    lines.forEach((line, index) => {
      if (!pattern.regex.test(line)) {
        return
      }
      if (isAllowedViolation(relativePath, pattern.label, line)) {
        return
      }
      violations.push(`${relativePath}:${index + 1}: ${pattern.label}`)
    })
    pattern.regex.lastIndex = 0
  }
}

for (const [relativePath, allowedLinePatterns] of allowedDirectApiLines.entries()) {
  const absolutePath = path.join(srcRoot, relativePath)
  if (!fs.existsSync(absolutePath)) {
    violations.push(`${relativePath}: configured transport exception file does not exist`)
    continue
  }

  const content = fs.readFileSync(absolutePath, 'utf8')
  for (const pattern of allowedLinePatterns) {
    if (!pattern.test(content)) {
      violations.push(`${relativePath}: configured transport exception no longer matches`)
    }
  }
}

if (violations.length > 0) {
  console.error('Direct API transport calls are not allowed in production frontend code.')
  console.error(
    'Use the generated client from src/api/client.ts, or add a narrow transport wrapper.',
  )
  console.error('')
  for (const violation of violations) {
    console.error(`- ${violation}`)
  }
  process.exit(1)
}
