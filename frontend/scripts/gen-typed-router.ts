import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRoutesContext, resolveOptions } from 'vue-router/unplugin'
import { typedRouterOptions } from '../src/router/typed-router-options'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const frontendRoot = path.resolve(scriptDir, '..')

async function main() {
  process.chdir(frontendRoot)

  const context = createRoutesContext(
    resolveOptions({
      ...typedRouterOptions,
      root: frontendRoot,
      watch: false,
    }),
  )

  await context.scanPages(false)
  context.stopWatcher()
}

main().catch((error: unknown) => {
  console.error('Failed to generate typed router:', error)
  process.exit(1)
})
