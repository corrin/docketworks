import { defineConfig } from '@hey-api/openapi-ts'

export default defineConfig({
  // v2's live schema, exported by scripts/checks/export_openapi.py.
  // NOT schema.yml — that is v1's frozen baseline and the left-hand side of
  // scripts/checks/schema_parity_diff.py.
  input: 'schema.v2.yml',
  output: {
    path: 'src/api/generated',
    format: 'prettier',
  },
  plugins: ['@hey-api/client-axios', '@hey-api/sdk', 'zod', '@tanstack/react-query'],
})
