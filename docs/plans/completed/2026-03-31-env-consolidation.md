# Env Consolidation: Eliminate DRY Violations Between Backend and Frontend .env

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove duplicated environment variables between `/.env` (backend) and `/frontend/.env` by having test/tooling scripts resolve the backend .env by convention, and reading `APP_DOMAIN` from it instead of duplicating the domain in frontend vars.

**Architecture:** The frontend `.env` keeps only vars that genuinely belong to the frontend: `VITE_UAT_URL`, `VITE_WEEKEND_TIMESHEETS_ENABLED`, E2E test credentials, and Xero test credentials. All domain/URL config that duplicated `APP_DOMAIN` is removed. Test scripts find the backend `.env` at `../.env` relative to the frontend dir (confirmed by existing repo layout and UAT layout at `/opt/docketworks/instances/<name>/`). Shell scripts and TypeScript test utilities are updated to use this convention.

**Tech Stack:** TypeScript (Playwright/Node), Bash, Vite config

---

## What Changes

### Vars removed from frontend/.env (derived from backend .env instead)
- `VITE_FRONTEND_BASE_URL` → derived as `https://${APP_DOMAIN}` from backend `.env`
- `VITE_ALLOWED_HOSTS` → derived as `APP_DOMAIN` from backend `.env`
- `BACKEND_ENV_PATH` → resolved by convention (`../.env` relative to frontend dir)

### Vars kept in frontend/.env (frontend-only, no backend equivalent)
- `VITE_UAT_URL` — admin menu external link
- `VITE_WEEKEND_TIMESHEETS_ENABLED` — feature flag
- `E2E_TEST_USERNAME` / `E2E_TEST_PASSWORD` — test credentials
- `XERO_USERNAME` / `XERO_PASSWORD` — Xero OAuth test credentials

### Files modified
- `frontend/tests/scripts/db-backup-utils.ts` — resolve backend .env by convention instead of `BACKEND_ENV_PATH`
- `frontend/playwright.config.ts` — derive `baseURL` from backend `APP_DOMAIN`
- `frontend/tests/scripts/global-setup.ts` — read `APP_DOMAIN` from backend .env
- `frontend/tests/scripts/xero-login.ts` — read `APP_DOMAIN` from backend .env
- `frontend/scripts/capture-screenshots.ts` — read `APP_DOMAIN` from backend .env
- `frontend/vite.config.ts` — read `APP_DOMAIN` from backend .env for `allowedHosts`
- `frontend/tests/scripts/backup-db.sh` — resolve backend .env by convention
- `frontend/tests/scripts/restore-db.sh` — resolve backend .env by convention
- `frontend/.env` — remove duplicated vars
- `frontend/.env.example` — update to match
- `frontend/env.d.ts` — remove `VITE_ALLOWED_HOSTS` from `ImportMetaEnv`
- `scripts/server/templates/frontend-env-instance.template` — remove duplicated vars

---

### Task 1: Add `getBackendEnv()` helper to db-backup-utils.ts

The core change: resolve backend .env by walking up to `../.env` from the frontend dir, and export a function that returns all backend env vars (including `APP_DOMAIN`). This replaces the `BACKEND_ENV_PATH` indirection.

**Files:**
- Modify: `frontend/tests/scripts/db-backup-utils.ts:40-70`

- [ ] **Step 1: Replace `resolveBackendEnvPath` with convention-based resolution**

In `frontend/tests/scripts/db-backup-utils.ts`, replace the `resolveBackendEnvPath` function:

```typescript
// OLD: reads BACKEND_ENV_PATH from frontend .env
function resolveBackendEnvPath(frontendDir: string): string {
  const frontendEnvPath = path.join(frontendDir, '.env')
  // ... reads BACKEND_ENV_PATH from frontend .env ...
}
```

With:

```typescript
function resolveBackendEnvPath(frontendDir: string): string {
  const backendEnvPath = path.join(frontendDir, '..', '.env')
  if (!fs.existsSync(backendEnvPath)) {
    throw new Error(
      `Backend .env not found at ${backendEnvPath}. ` +
        'Expected at repo root (one level up from frontend/).',
    )
  }
  return backendEnvPath
}
```

- [ ] **Step 2: Add `getBackendEnv()` export**

Add this exported function after `getBackupsDir()`:

```typescript
/**
 * Parse the backend .env and return all key-value pairs.
 * Used by Playwright config and test scripts to read APP_DOMAIN, DB creds, etc.
 */
export function getBackendEnv(): Record<string, string> {
  const frontendDir = getFrontendDir()
  const backendEnvPath = resolveBackendEnvPath(frontendDir)
  return parseEnvFile(backendEnvPath)
}
```

Also export `parseEnvFile` (change from bare `function` to `export function`) since it's useful standalone.

- [ ] **Step 3: Update `getDbConfig()` to use the simplified resolution**

`getDbConfig()` already calls `resolveBackendEnvPath` — no changes needed to its body since we changed the function it calls. Verify it still works by reading the function.

- [ ] **Step 4: Commit**

```bash
git add frontend/tests/scripts/db-backup-utils.ts
git commit -m "refactor: resolve backend .env by convention instead of BACKEND_ENV_PATH"
```

---

### Task 2: Update playwright.config.ts to derive baseURL from APP_DOMAIN

**Files:**
- Modify: `frontend/playwright.config.ts`

- [ ] **Step 1: Import `getBackendEnv` and derive baseURL**

Replace the current config:

```typescript
import { defineConfig, devices } from '@playwright/test'
import dotenv from 'dotenv'
import fs from 'fs'
import path from 'path'

// Load environment variables from .env, then override with .env.test when present.
dotenv.config()
const testEnvPath = path.resolve(process.cwd(), '.env.test')
if (fs.existsSync(testEnvPath)) {
  dotenv.config({ path: testEnvPath, override: true })
}

export default defineConfig({
```

With:

```typescript
import { defineConfig, devices } from '@playwright/test'
import dotenv from 'dotenv'
import fs from 'fs'
import path from 'path'
import { getBackendEnv } from './tests/scripts/db-backup-utils'

// Load environment variables from .env, then override with .env.test when present.
dotenv.config()
const testEnvPath = path.resolve(process.cwd(), '.env.test')
if (fs.existsSync(testEnvPath)) {
  dotenv.config({ path: testEnvPath, override: true })
}

const backendEnv = getBackendEnv()
const appDomain = backendEnv.APP_DOMAIN
if (!appDomain) {
  throw new Error('APP_DOMAIN must be set in backend .env')
}
const baseURL = `https://${appDomain}`

export default defineConfig({
```

- [ ] **Step 2: Use the derived baseURL**

Replace:
```typescript
    baseURL: process.env.VITE_FRONTEND_BASE_URL || 'http://localhost:5173',
```

With:
```typescript
    baseURL,
```

- [ ] **Step 3: Commit**

```bash
git add frontend/playwright.config.ts
git commit -m "refactor: derive Playwright baseURL from backend APP_DOMAIN"
```

---

### Task 3: Update global-setup.ts and xero-login.ts to use APP_DOMAIN

**Files:**
- Modify: `frontend/tests/scripts/global-setup.ts`
- Modify: `frontend/tests/scripts/xero-login.ts`

- [ ] **Step 1: Update global-setup.ts**

Replace the `checkXeroConnected` function's URL resolution:

```typescript
async function checkXeroConnected(): Promise<boolean> {
  const frontendUrl = process.env.VITE_FRONTEND_BASE_URL
  if (!frontendUrl) {
    throw new Error('VITE_FRONTEND_BASE_URL must be set in .env')
  }
```

With:

```typescript
async function checkXeroConnected(): Promise<boolean> {
  const backendEnv = getBackendEnv()
  const appDomain = backendEnv.APP_DOMAIN
  if (!appDomain) {
    throw new Error('APP_DOMAIN must be set in backend .env')
  }
  const frontendUrl = `https://${appDomain}`
```

Add the import at the top:
```typescript
import { getBackendEnv } from './db-backup-utils'
```

- [ ] **Step 2: Update xero-login.ts**

Replace:
```typescript
  const frontendUrl = process.env.VITE_FRONTEND_BASE_URL
```
and:
```typescript
  if (!frontendUrl) {
    throw new Error('VITE_FRONTEND_BASE_URL must be set in .env')
  }
```

With:
```typescript
  const backendEnv = getBackendEnv()
  const appDomain = backendEnv.APP_DOMAIN
  if (!appDomain) {
    throw new Error('APP_DOMAIN must be set in backend .env')
  }
  const frontendUrl = `https://${appDomain}`
```

Add the import at the top:
```typescript
import { getBackendEnv } from './db-backup-utils'
```

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/scripts/global-setup.ts frontend/tests/scripts/xero-login.ts
git commit -m "refactor: use APP_DOMAIN from backend .env in test scripts"
```

---

### Task 4: Update capture-screenshots.ts

**Files:**
- Modify: `frontend/scripts/capture-screenshots.ts`

- [ ] **Step 1: Replace VITE_FRONTEND_BASE_URL usage**

Find (around line 235):
```typescript
  const baseUrl = process.env.VITE_FRONTEND_BASE_URL || 'http://localhost:5173'
```

Replace with:
```typescript
  const backendEnv = getBackendEnv()
  const appDomain = backendEnv.APP_DOMAIN
  if (!appDomain) {
    throw new Error('APP_DOMAIN must be set in backend .env')
  }
  const baseUrl = `https://${appDomain}`
```

Add at the top of the file:
```typescript
import { getBackendEnv } from '../tests/scripts/db-backup-utils'
```

- [ ] **Step 2: Commit**

```bash
git add frontend/scripts/capture-screenshots.ts
git commit -m "refactor: use APP_DOMAIN in capture-screenshots"
```

---

### Task 5: Update vite.config.ts to read APP_DOMAIN from backend .env

**Files:**
- Modify: `frontend/vite.config.ts`

- [ ] **Step 1: Read APP_DOMAIN from backend .env for allowedHosts**

Replace:
```typescript
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
import { defineConfig, loadEnv } from 'vite'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')

  const allowedHosts = [
    'localhost',
    ...(env.VITE_ALLOWED_HOSTS ? env.VITE_ALLOWED_HOSTS.split(',').map((host) => host.trim()) : []),
  ]
```

With:
```typescript
import fs from 'node:fs'
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import vue from '@vitejs/plugin-vue'
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

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const appDomain = readBackendAppDomain()

  const allowedHosts = ['localhost', appDomain]
```

Note: We use a local function here rather than importing from `db-backup-utils.ts` because vite.config.ts runs in a different context (Vite's own Node process) and importing test utilities from the config would create a dependency from build tooling to test tooling. A simple inline read is cleaner.

- [ ] **Step 2: Commit**

```bash
git add frontend/vite.config.ts
git commit -m "refactor: read APP_DOMAIN from backend .env in vite config"
```

---

### Task 6: Update shell scripts to resolve backend .env by convention

**Files:**
- Modify: `frontend/tests/scripts/backup-db.sh`
- Modify: `frontend/tests/scripts/restore-db.sh`

- [ ] **Step 1: Update backup-db.sh**

Replace lines 10-18:
```bash
# Load BACKEND_ENV_PATH from frontend .env
if [ -f "$FRONTEND_DIR/.env" ]; then
    BACKEND_ENV_PATH=$(grep -E '^BACKEND_ENV_PATH=' "$FRONTEND_DIR/.env" | cut -d'=' -f2)
fi

if [ -z "$BACKEND_ENV_PATH" ] || [ ! -f "$BACKEND_ENV_PATH" ]; then
    echo "Error: Backend .env not found. Set BACKEND_ENV_PATH in frontend .env"
    exit 1
fi
```

With:
```bash
# Backend .env is always one level up from frontend/
BACKEND_ENV_PATH="$FRONTEND_DIR/../.env"

if [ ! -f "$BACKEND_ENV_PATH" ]; then
    echo "Error: Backend .env not found at $BACKEND_ENV_PATH"
    exit 1
fi
```

- [ ] **Step 2: Update restore-db.sh**

Same replacement as backup-db.sh — replace lines 10-18:
```bash
# Load BACKEND_ENV_PATH from frontend .env
if [ -f "$FRONTEND_DIR/.env" ]; then
    BACKEND_ENV_PATH=$(grep -E '^BACKEND_ENV_PATH=' "$FRONTEND_DIR/.env" | cut -d'=' -f2)
fi

if [ -z "$BACKEND_ENV_PATH" ] || [ ! -f "$BACKEND_ENV_PATH" ]; then
    echo "Error: Backend .env not found. Set BACKEND_ENV_PATH in frontend .env"
    exit 1
fi
```

With:
```bash
# Backend .env is always one level up from frontend/
BACKEND_ENV_PATH="$FRONTEND_DIR/../.env"

if [ ! -f "$BACKEND_ENV_PATH" ]; then
    echo "Error: Backend .env not found at $BACKEND_ENV_PATH"
    exit 1
fi
```

- [ ] **Step 3: Commit**

```bash
git add frontend/tests/scripts/backup-db.sh frontend/tests/scripts/restore-db.sh
git commit -m "refactor: resolve backend .env by convention in shell scripts"
```

---

### Task 7: Clean up .env files, env.d.ts, and server template

**Files:**
- Modify: `frontend/.env`
- Modify: `frontend/.env.example`
- Modify: `frontend/env.d.ts`
- Modify: `scripts/server/templates/frontend-env-instance.template`

- [ ] **Step 1: Update frontend/.env**

Replace entire contents with:
```
# E2E test credentials (login to the app)
E2E_TEST_USERNAME=defaultadmin@example.com
E2E_TEST_PASSWORD=Default-admin-password

# Xero login credentials (for automated OAuth flow during restore)
XERO_USERNAME=corrin.lakeland@cmeconnect.com
XERO_PASSWORD="uExBd9dEG6wuyd"

VITE_UAT_URL=https://msm-uat.docketworks.site

# Weekend timesheets feature flag
VITE_WEEKEND_TIMESHEETS_ENABLED=false
```

Removed: `BACKEND_ENV_PATH`, `VITE_FRONTEND_BASE_URL`, `VITE_ALLOWED_HOSTS`.

- [ ] **Step 2: Update frontend/.env.example**

Replace entire contents with:
```
# UAT site URL - opens in new tab from admin menu
VITE_UAT_URL=https://your-client.docketworks.site

# Weekend timesheets feature flag
VITE_WEEKEND_TIMESHEETS_ENABLED=false

# E2E test credentials
E2E_TEST_USERNAME=admin@example.com
E2E_TEST_PASSWORD=password

# Xero login credentials (for E2E automated OAuth flow)
XERO_USERNAME=username@example.com
XERO_PASSWORD="password"
```

- [ ] **Step 3: Update frontend/env.d.ts**

Remove `VITE_ALLOWED_HOSTS` from `ImportMetaEnv`:

```typescript
interface ImportMetaEnv {
  readonly VITE_WEEKEND_TIMESHEETS_ENABLED: string
  readonly VITE_UAT_URL?: string
}
```

- [ ] **Step 4: Update server template**

Replace `scripts/server/templates/frontend-env-instance.template` contents with:
```
# E2E test credentials (admin user on this instance)
E2E_TEST_USERNAME=__E2E_TEST_USERNAME__
E2E_TEST_PASSWORD=__E2E_TEST_PASSWORD__

VITE_UAT_URL=https://__CLIENT__-uat.__DOMAIN__

# Weekend timesheets feature flag
VITE_WEEKEND_TIMESHEETS_ENABLED=false

# Xero login credentials (for automated OAuth flow during restore)
XERO_USERNAME=__XERO_USERNAME__
XERO_PASSWORD="__XERO_PASSWORD__"
```

Removed: `BACKEND_ENV_PATH`, `VITE_FRONTEND_BASE_URL`, `VITE_ALLOWED_HOSTS`, `VITE_AUTH_METHOD`.

- [ ] **Step 5: Commit**

```bash
git add frontend/.env frontend/.env.example frontend/env.d.ts scripts/server/templates/frontend-env-instance.template
git commit -m "refactor: remove duplicated env vars from frontend .env files"
```

---

### Task 8: Verify no remaining references to removed vars

- [ ] **Step 1: Search for stale references**

```bash
cd /home/corrin/src/docketworks
grep -r 'VITE_FRONTEND_BASE_URL\|VITE_ALLOWED_HOSTS\|BACKEND_ENV_PATH' --include='*.ts' --include='*.sh' --include='*.py' --include='*.md' --include='*.yml' --include='*.template' .
```

Any hits in code files (not docs) indicate missed updates. Fix them.

- [ ] **Step 2: Update any documentation references**

Documentation files (`.md`) that reference `VITE_FRONTEND_BASE_URL` or `BACKEND_ENV_PATH` should be updated to reference `APP_DOMAIN` in the backend `.env` instead.

- [ ] **Step 3: Run type-check**

```bash
cd frontend && npm run type-check
```

- [ ] **Step 4: Final commit if any doc/fixup changes**

```bash
git add -u
git commit -m "docs: update env var references after consolidation"
```
