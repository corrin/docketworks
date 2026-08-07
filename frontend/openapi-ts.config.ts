import { defineConfig } from '@hey-api/openapi-ts'

export default defineConfig({
  // v2's live schema, exported by scripts/checks/export_openapi.py. CI fails
  // if this file is stale, because a client generated from a stale schema
  // describes an API that no longer exists — and tsc compiles it happily.
  input: 'schema.v2.yml',
  output: {
    path: 'src/api/generated',
    format: 'prettier',
  },
  plugins: ['@hey-api/client-axios', '@hey-api/sdk', 'zod', '@tanstack/react-query'],
})
