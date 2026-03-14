# Repository Guidelines

## Project Structure & Module Organization

This Vue 3 + TypeScript frontend keeps production-ready sources under `src/`. Feature views live in `src/views`, reusable UI in `src/components`, stateful logic in `src/stores`, and shared composables in `src/composables`. Generated API clients and schema helpers reside in `src/api` and `src/schemas`, both of which mirror `schema.yml`. Static assets belong in `public/`, repo docs and ADRs in `docs/`, automation in `scripts/`, and build artifacts in `dist/` (do not edit by hand).

## Build, Test, and Development Commands

- `npm install` once per environment to sync dependencies.
- `npm run dev` updates the schema and starts the Vite dev server on http://localhost:5173.
- `npm run build` runs type-checking and emits the optimized bundle into `dist/`.
- `npm run preview` serves the latest build for manual QA.
- `npm run lint` applies ESLint fixes across TypeScript and Vue files.
- `npm run format` runs Prettier on `src/` for consistent spacing.
- `npm run update-schema` refreshes `schema.yml` and regenerates the OpenAPI client before API work.

## Coding Style & Naming Conventions

Prettier 3 handles formatting; keep two-space indentation, single quotes, and trailing newlines. Vue single-file components prefer the `<script setup lang="ts">` pattern for brevity. Name components in PascalCase (`JobDetailCard.vue`) and store/composable modules in camelCase (`useJobFilters.ts`). Tailwind utility classes drive styling—add shared tokens or overrides in `src/assets/main.css`. Centralize domain types in `src/types` and reuse exported interfaces instead of redefining structures.

## Testing Guidelines

Vitest powers unit tests alongside `@vue/test-utils`. Place specs in a colocated `__tests__` folder and name files `ComponentName.test.ts`, matching the existing suites. Run `npx vitest --run` before pushes or `npx vitest --ui` while iterating; add assertions for Pinia store mutations and emitted events on new features.

## Commit & Pull Request Guidelines

Git history favors concise, present-tense summaries (`Fix modal guard`, `Improve type handling`). Commit related changes together and reference issue IDs when available. Simple Git Hooks run `npm run lint` and `npm run type-check` on pre-push—ensure they pass locally alongside targeted `vitest` runs. In PRs, provide context, testing notes, and screenshots or schema diffs whenever the UI or API surface changes.
