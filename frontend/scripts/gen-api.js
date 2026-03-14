#!/usr/bin/env node
/**
 * scripts/gen-api.js
 *
 * Programmatically generate the Zodios client from `schema.yml`,
 * then append `export { endpoints };` so we can import the endpoints array.
 */

import SwaggerParser from '@apidevtools/swagger-parser'
import { generateZodClientFromOpenAPI } from 'openapi-zod-client'
import { execSync } from 'child_process'
import fs from 'fs/promises'
import path from 'path'

async function main() {
  // 1. Resolve paths
  const specPath = path.resolve(process.cwd(), 'schema.yml')
  const outputPath = path.resolve(process.cwd(), 'src/api/generated/api.ts')

  // 2. Load & parse the OpenAPI spec
  const openApiDoc = await SwaggerParser.parse(specPath)

  // 3. Generate the client + schemas
  await generateZodClientFromOpenAPI({
    openApiDoc,
    distPath: outputPath,
    options: {
      exportSchemas: true, // same as --export-schemas
      apiClientName: 'api', // generates `export const api = new Zodios(...)`
      withAlias: true,
      additionalPropertiesDefaultValue: false, // don't add .passthrough() to every schema
    },
    prettierPath: '.prettierrc.json', // Use project's prettier config
  })

  // 4. Append `export { endpoints };` if it's missing
  let content = await fs.readFile(outputPath, 'utf-8')
  if (!/export\s+\{\s*endpoints\s*\}/.test(content)) {
    content += '\nexport { endpoints };\n'
    await fs.writeFile(outputPath, content, 'utf-8')
    console.log('✅ Appended `export { endpoints };`')
  } else {
    console.log('ℹ️  `export { endpoints };` already present')
  }

  // 5. Format with project's prettier config for consistency
  execSync(`npx prettier --write "${outputPath}"`, { stdio: 'inherit' })
  console.log('✅ Applied Prettier formatting')
}

main().catch((err) => {
  console.error('❌ Generation failed:', err)
  process.exit(1)
})
