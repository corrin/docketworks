# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

Project: Jobs Manager Frontend (Vue 3 + TypeScript + Vite)

Commands

- Install deps: npm install
- Start dev server: npm run dev
  - Includes update-schema to regenerate the OpenAPI client if the backend is reachable
- Build: npm run build
  - Includes update-schema, then type-check and production build
- Preview build: npm run preview
- Type-check: npm run type-check
- Lint (autofix): npm run lint
- Format: npm run format
- Regenerate API client from OpenAPI schema: npm run update-schema
  - Fetches http://localhost:8000/api/schema/ into schema.yml, then runs scripts/gen-api.js
  - If the backend is unavailable, keeps existing schema.yml and regenerates the client from it

Environment

- .env.example documents these variables:
  - VITE_API_BASE_URL: Backend API base URL
  - VITE_ALLOWED_HOSTS: Comma-separated list used by Vite dev server allowedHosts
  - VITE_UAT_URL: UAT environment URL
- Vite config reads VITE_ALLOWED_HOSTS to populate dev server allowedHosts.

Tech stack and tooling

- Framework/build: Vue 3 (Composition API), Vite, TypeScript
- State/routing: Pinia (stores), Vue Router (src/router)
- Styling: Tailwind CSS v4 (via @tailwindcss/vite plugin), styles in src/assets/main.css
- API client: openapi-zod-client + Zodios generated into src/api/generated/api.ts (via scripts/gen-api.js)
- HTTP: Axios with interceptors in src/plugins/axios.ts
- Lint/Format: ESLint (flat config in eslint.config.ts) + Prettier (.prettierrc.json)
- Aliases: @ -> ./src (see tsconfig.json and vite.config.ts)

Critical rules (from CLAUDE.md)

- Schema rule: Do NOT model backend database data in the frontend.
  - Use backend-provided schemas only (generated types from src/api/generated).
  - Never create local types mirroring API data, never comment out broken imports, never use // @ts-ignore for missing schemas.
- Backend coordination: You cannot read the backend repo here; coordinate through the user for business logic, API contract questions, or schema updates.
- No Fallbacks rule: Don’t add fallbacks for our own API/config values (e.g., avoid job.job_number || job.number and avoid env fallbacks for VITE_API_BASE_URL).

High-level architecture

- Entry and app composition
  - src/main.ts bootstraps Vue, installs Pinia and Router, loads Axios plugin, and mounts App.vue.
  - Global EventSource polyfill is configured for SSE support.
- Routing: src/router/index.ts
  - Public route: /login
  - Auth-protected routes: Kanban (/kanban) plus job, timesheet, purchasing, admin, reports pages.
  - Navigation guards:
    - Sets document.title from route meta.
    - For routes with meta.requiresAuth, verifies session via auth store (userIsLogged) and redirects to /login if unauthenticated.
    - Guests are redirected from guest-only routes when already authenticated.
- Authentication/state: src/stores/auth.ts (Pinia)
  - user/isLoading/error reactive state, isAuthenticated/fullName computed.
  - login: token acquisition via generated API, then fetches current user (accounts_me_retrieve).
  - logout: posts to /accounts/logout/ (Axios), clears frontend state.
  - userIsLogged: verifies session by calling accounts_me_retrieve.
- Axios integration: src/plugins/axios.ts
  - Base URL from import.meta.env.VITE_API_BASE_URL (see note in CLAUDE.md about avoiding fallbacks).
  - withCredentials enabled; response interceptor handles 401 by routing to /login and invoking Xero auth flow when required.
- API client generation: scripts/gen-api.js
  - Parses schema.yml, generates Zod schemas and Zodios client into src/api/generated/api.ts, ensures export { endpoints } is present.
  - src/api/client.ts builds a Zodios instance with the Axios instance and exposes api and endpoints.
- Domains/features
  - Views under src/views/ for Kanban, job management, timesheets (daily/weekly/entry), purchasing (PO, stock, mappings, pricing), admin screens, reports (KPI, job aging, staff performance), and quoting chat.
  - Composables under src/composables/ (e.g., useKanban for DnD and filtering logic).
  - Services layer under src/services/ wraps API access patterns.
  - Schemas in src/schemas/ contain Zod definitions for non-API UI data and helpers.
  - Components under src/components/ and UI toolkit integration via shadcn-vue (see components.json), AG Grid setup in src/plugins/ag-grid.ts.

Development workflow notes

- API schema workflow
  - During dev/build, update-schema will attempt to fetch the backend OpenAPI schema.
  - If the backend isn’t running, the client regenerates from the existing schema.yml to keep the build unblocked.
  - Coordinate with backend for any contract changes; do not create local stand-ins for backend data.
- Hooks
  - simple-git-hooks is configured via package.json; pre-commit runs lint-staged (Prettier and ESLint), pre-push runs lint and type-check.

Testing

- No test runner is configured in package.json at this time. If tests are added in the future, include the exact commands here (including how to run a single test).
