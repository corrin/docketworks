import { defineConfig } from '@hey-api/openapi-ts'

export default defineConfig({
  input: 'schema.yml',
  output: {
    path: 'src/api/generated',
    format: 'prettier',
  },
  plugins: ['@hey-api/client-axios', '@hey-api/sdk', 'zod', '@tanstack/react-query'],
})
