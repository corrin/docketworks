# Monorepo Migration Plan

**Working directory:** `/home/corrin/src/docketworks`
**Status:** Backend cloned, origin set to `github.com/corrin/docketworks`

---

## Step 1: Import Frontend via Subtree Add

This places ALL frontend files under `frontend/` with full history preserved. Zero conflict risk.

```bash
git subtree add --prefix=frontend https://github.com/corrin/jobs_manager_front.git main
```

After this, every frontend file is under `frontend/` and every backend file is at root. No overlap.

Commit is created automatically by `git subtree add`.

---

## Step 2: Migrate and Merge Configuration

Frontend config files now live under `frontend/` but some need merging into root equivalents. For each file below: read the frontend version, merge relevant content into the root version, then remove the frontend copy.

### 2a: `.gitignore`

**Read:** `frontend/.gitignore`
**Merge into root `.gitignore`** — add these entries:

```gitignore
# Frontend
node_modules/
dist-ssr/
coverage/
*.local
*.tsbuildinfo
pnpm-lock.yaml
frontend/test-results/
frontend/playwright-report/
frontend/manual/.vitepress/cache/
frontend/manual/.vitepress/dist/
frontend/dist-manual/
frontend/dist/
```

**Remove:** `git rm frontend/.gitignore`

### 2b: `.github/dependabot.yml`

**Read:** `frontend/.github/dependabot.yml` (has npm ecosystem)
**Replace root `.github/dependabot.yml`** with merged version:

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /
    schedule:
      interval: weekly
    open-pull-requests-limit: 5

  - package-ecosystem: npm
    directory: /frontend
    schedule:
      interval: weekly
    open-pull-requests-limit: 5

  - package-ecosystem: github-actions
    directory: /
    schedule:
      interval: weekly
    open-pull-requests-limit: 5
```

### 2c: `.github/workflows/ci.yml`

**Read:** `frontend/.github/workflows/ci.yml` (has frontend-lint, frontend-type-check, frontend-unit-tests jobs)
**Replace root `.github/workflows/ci.yml`** with combined version:

```yaml
name: CI

on:
  push:
    branches: ["**"]
  pull_request:
    branches: [main, develop]

jobs:
  backend:
    name: Backend Checks
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: 3.12

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install poetry pre-commit
          poetry install --with dev

      - name: Setup dummy .env
        run: cp .env.precommit .env

      - name: Run pre-commit
        uses: pre-commit/action@v3.0.1
        with:
          extra_args: --all-files

  frontend-lint:
    name: Frontend Lint
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npx prettier --check .
      - run: npx eslint .

  frontend-type-check:
    name: Frontend Type Check
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npm run type-check

  frontend-unit-tests:
    name: Frontend Unit Tests
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: frontend
    env:
      VITE_API_BASE_URL: http://localhost:8000
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'
          cache-dependency-path: frontend/package-lock.json
      - run: npm ci
      - run: npm run test:unit
```

### 2d: `.github/workflows/cd.yml`

**Read:** `frontend/.github/workflows/cd.yml` — note the more robust SSM polling logic.

The backend `cd.yml` already deploys to both machines via `deploy.sh` which handles frontend build. The frontend's separate CD is no longer needed since `deploy.sh` (updated in Step 4) will build frontend from `frontend/`.

**Keep root `cd.yml` as-is.** No changes needed.

### 2e: `.github/pull_request_template.md`

**Read both versions**, pick the better one. The original plan specified keeping the frontend version:

```bash
cp frontend/.github/pull_request_template.md .github/pull_request_template.md
git add .github/pull_request_template.md
```

### 2f: Remove frontend `.github/`

After migrating everything above:

```bash
git rm -rf frontend/.github
```

### 2g: Remove other frontend-only root config

These are handled at root level or not needed:

```bash
git rm frontend/.gitattributes
git rm -rf frontend/.claude
git rm frontend/.mcp.json
git rm -rf frontend/.serena
git rm -rf frontend/.kilocode
```

`frontend/.editorconfig`, `frontend/.prettierrc.json`, `frontend/.nvmrc`, `frontend/.husky/` — **keep these** in `frontend/`, they're frontend tooling config.

`frontend/CLAUDE.md`, `frontend/AGENTS.md` — **keep these**, they're frontend-specific AI instructions.

`frontend/.env.example` — **keep this**, it documents frontend env vars.

### Commit:
```bash
git add -A
git commit -m "Migrate frontend config into root and clean up duplicates"
```

---

## Step 3: Update deploy.sh

**File:** `scripts/deploy.sh`

### Change `build_frontend()`:

**From:**
```bash
build_frontend() {
    [ "$ENV" = "SCHEDULER" ] && return
    echo "=== Building Vue.js frontend ==="
    cd "$USER_DIR/jobs_manager_front"
    npm install
    npm run build
}
```

**To:**
```bash
build_frontend() {
    [ "$ENV" = "SCHEDULER" ] && return
    echo "=== Building Vue.js frontend ==="
    cd "$PROJECT_DIR/frontend"
    npm install
    npm run build
}
```

### Remove `USER_DIR` from `detect_environment()`:

**From:**
```bash
detect_environment() {
    case "$(hostname)" in
        "msm")
            ENV="PROD"; PROJECT_DIR="/home/django_user/jobs_manager"
            USER_DIR="/home/django_user"; APP_USER="django_user" ;;
        "uat-scheduler")
            ENV="SCHEDULER"; PROJECT_DIR="/opt/workflow_app/jobs_manager"
            USER_DIR="/opt/workflow_app"; APP_USER="ubuntu" ;;
        "uat"|"uat-frontend")
            ENV="UAT"; PROJECT_DIR="/opt/workflow_app/jobs_manager"
            USER_DIR="/opt/workflow_app"; APP_USER="ubuntu" ;;
        *)
            echo "ERROR: Unknown hostname $(hostname)"; exit 1 ;;
    esac
}
```

**To:**
```bash
detect_environment() {
    case "$(hostname)" in
        "msm")
            ENV="PROD"; PROJECT_DIR="/home/django_user/jobs_manager"
            APP_USER="django_user" ;;
        "uat-scheduler")
            ENV="SCHEDULER"; PROJECT_DIR="/opt/workflow_app/jobs_manager"
            APP_USER="ubuntu" ;;
        "uat"|"uat-frontend")
            ENV="UAT"; PROJECT_DIR="/opt/workflow_app/jobs_manager"
            APP_USER="ubuntu" ;;
        *)
            echo "ERROR: Unknown hostname $(hostname)"; exit 1 ;;
    esac
}
```

### Commit:
```bash
git commit -am "Update deploy.sh for monorepo frontend path"
```

---

## Step 4: Update frontend deploy script

**File:** `frontend/scripts/deploy_frontend.sh`

### Change PROJECT_PATH:

**From:**
```bash
PROJECT_PATH="/opt/workflow_app/jobs_manager_front"
```

**To:**
```bash
PROJECT_PATH="/opt/workflow_app/jobs_manager/frontend"
```

### Update git/deploy logic to work from monorepo root:

**From:**
```bash
main() {
    echo "Starting frontend deployment..."

    cd "$PROJECT_PATH"
    CURRENT_USER="$(whoami)"

    # Update code from git
    git switch main
    git fetch origin main
    git reset --hard origin/main
    chmod +x scripts/deploy_frontend.sh
    chown -R "$CURRENT_USER:$CURRENT_USER" "$PROJECT_PATH"
```

**To:**
```bash
main() {
    echo "Starting frontend deployment..."

    MONOREPO_ROOT="$(dirname "$(dirname "$PROJECT_PATH")")"
    cd "$MONOREPO_ROOT"
    CURRENT_USER="$(whoami)"

    # Update code from git
    git switch main
    git fetch origin main
    git reset --hard origin/main
    chmod +x frontend/scripts/deploy_frontend.sh
    chown -R "$CURRENT_USER:$CURRENT_USER" "$MONOREPO_ROOT"

    cd "$PROJECT_PATH"
```

### Commit:
```bash
git commit -am "Update frontend deploy script for monorepo"
```

---

## Step 5: Unify pre-commit hooks

### Add frontend lint-staged to `.pre-commit-config.yaml`:

Append to the end of the `- repo: local` hooks list:

```yaml
      - id: frontend-lint-staged
        name: Frontend lint-staged
        entry: bash -c 'cd frontend && npx lint-staged'
        language: system
        files: '^frontend/.*\.(js|ts|vue|json|md|yml|css)$'
        pass_filenames: false
```

### Clean up `frontend/package.json`:

**Remove** the `simple-git-hooks` config block:
```json
  "simple-git-hooks": {
    "pre-commit": "npx lint-staged",
    "pre-push": "npm run test:unit && npm run lint && npm run type-check"
  }
```

**Remove** the `"prepare"` script:
```json
    "prepare": "simple-git-hooks",
```

**Remove** from devDependencies:
```json
    "simple-git-hooks": "^2.13.0",
```

**Keep** the `"lint-staged"` config block — it's used by the new pre-commit hook.

### Remove frontend .husky/:

Since we're using pre-commit now instead of simple-git-hooks/husky:
```bash
git rm -rf frontend/.husky
```

### Commit:
```bash
git add -A
git commit -m "Unify pre-commit hooks for monorepo"
```

---

## Step 6: Verify

```bash
# History preserved
git log --oneline | head -20
git log --oneline --follow -- frontend/src/App.vue | head -10

# File structure correct
ls frontend/src/
ls frontend/package.json
ls scripts/deploy.sh

# No frontend files leaked to root
# These should NOT exist at root: src/ public/ package.json index.html tsconfig.json
test ! -d src && test ! -d public && test ! -f package.json && echo "CLEAN" || echo "CONTAMINATED"
```

---

## Step 7: Push

```bash
git push -u origin main
```

---

## Out of scope (manual steps for later):
- **GitHub repo settings:** secrets, variables, branch protection on `docketworks`
- **Server-side cutover:** clone docketworks on each server, symlink, restart services, update nginx
- **Archive old repos:** update READMEs, archive on GitHub
