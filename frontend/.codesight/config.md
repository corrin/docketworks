# Config

## Environment Variables

- `APP_URL` **required** — scripts/capture_metrics.cjs
- `BASE_URL` **required** — src/router/index.ts
- `CI` **required** — playwright.config.ts
- `DEBUG` **required** — tests/fixtures/auth.ts
- `DJANGO_PASSWORD` **required** — scripts/capture_metrics.cjs
- `DJANGO_USER` **required** — scripts/capture_metrics.cjs
- `E2E_TEST_PASSWORD` (has default) — .env.example
- `E2E_TEST_USERNAME` (has default) — .env.example
- `PLAYWRIGHT_BROWSER_CHANNEL` **required** — tests/scripts/xero-login.ts
- `VITE_APP_NAME` (has default) — .env
- `VITE_UAT_URL` (has default) — .env.example
- `XERO_PASSWORD` (has default) — .env.example
- `XERO_USERNAME` (has default) — .env.example

## Config Files

- `.env.example`
- `tsconfig.json`
- `vite.config.ts`

## Key Dependencies

- tailwindcss: ^4.2.2
- vue: ^3.5.13
- zod: ^3.25.55
