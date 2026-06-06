import { mkdtemp, readFile, rm } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRoutesContext, resolveOptions } from 'vue-router/unplugin'
import { routerAutoOptions, typedRouterDtsPath } from '../router-auto-options'

const frontendRoot = fileURLToPath(new URL('..', import.meta.url))
const actualDtsPath = path.resolve(frontendRoot, typedRouterDtsPath)

async function writeTypedRouter(dtsPath: string): Promise<void> {
  const options = resolveOptions({
    ...routerAutoOptions,
    root: frontendRoot,
    dts: dtsPath,
    watch: false,
  })
  const context = createRoutesContext(options)

  try {
    await context.scanPages(false)
  } finally {
    context.stopWatcher()
  }
}

async function checkTypedRouter(): Promise<void> {
  const tmpDir = await mkdtemp(path.join(os.tmpdir(), 'docketworks-typed-router-'))
  const expectedDtsPath = path.join(tmpDir, 'typed-router.d.ts')

  try {
    await writeTypedRouter(expectedDtsPath)
    const [actual, expected] = await Promise.all([
      readFile(actualDtsPath, 'utf8'),
      readFile(expectedDtsPath, 'utf8'),
    ])

    if (actual !== expected) {
      console.error(`${typedRouterDtsPath} is stale. Run npm run gen:typed-router from frontend/.`)
      process.exitCode = 1
    }
  } finally {
    await rm(tmpDir, { recursive: true, force: true })
  }
}

if (process.argv.includes('--check')) {
  await checkTypedRouter()
} else {
  await writeTypedRouter(actualDtsPath)
}
