# Frontend Development Rules

Vue 3 + TypeScript jobs management app with multi-user editing, autosave, and optimistic concurrency. API contracts defined in OpenAPI schema.

The architectural decisions behind these rules live in `../docs/adr/`. Most directly relevant: API access (rules 1–7) → ADR 0021 (generated client only); concurrency (rules 22–25) → ADR 0003 (ETag) and ADR 0004 (delta envelope); the frontend/backend boundary → ADR 0020. The remaining rules below are Vue/TS conventions and operational specifics.

---

## Backend Communication

The backend (Django) is in the repo root. The frontend and backend are in the same repo but have separate conventions and tooling.

**Don't modify backend code from a frontend context.** If you're working on frontend code (typically as a subagent scoped to `frontend/`), don't edit files outside `frontend/`. If the frontend needs a new endpoint or data shape, write requirements as spec documents (in `docs/plans/`) and present them to the user.

---

## Critical Rules

### Schema-Driven Development

1. Backend schema is source of truth — types from `schema.yml`
2. Never manually type API responses — use `z.infer<typeof schemas.X>`
3. Only use generated `api` client — never raw fetch/axios
4. Missing endpoint? Stop and request backend implementation
5. After schema updates: `npm run update-schema && npm run gen:api`
6. Never edit `/src/api/generated/api.ts`
7. Never work around backend issues

### State Management

8. Immutable updates: `state.value = { ...state.value, [key]: newValue }`
9. Never mutate objects directly — Vue 3 reactivity won't detect it
10. Stores manage state, services call APIs
11. Use `ref()` for state, `computed()` for getters
12. Store entities by ID: `Record<string, Entity>`
13. Stores don't return promises — update state as side effects

### Type Safety

14. Let TypeScript infer types
15. Use `null` for nullable fields, not `undefined`
16. Validate with Zod: `schemas.X.parse(data)`
17. Strict mode enforced — no `any` without justification

### Component Architecture

18. Components use stores + composables — minimal direct API calls
19. Never mutate props — emit events
20. Use `<script setup lang="ts">` only
21. Import with `@/` alias — never `../../`

### Concurrency & Autosave

22. ETag headers managed automatically
23. Handle 412/428: reload data + notify user
24. Respect autosave's 500ms debounce
25. Optimistic updates must have rollback

### Error Handling

26. Every `console.error` must toast or throw — never silent failures

---

## File Organization

```
/src/api/          - Generated API client
/src/services/     - API calls + business logic
/src/stores/       - Pinia state management
/src/composables/  - Reusable reactive logic
/src/components/   - Vue components (domain/{domain}/, shared/, ui/)
/src/views/        - Page-level route components
/src/types/        - TypeScript types
/src/utils/        - Pure utilities
```

---

## Development Workflow

**Adding features:** Check endpoint exists in `/src/api/generated/api.ts` → if missing, request backend first → after added, run update-schema && gen:api → implement using generated types

**API calls:** `import { api } from '@/api/client'` + `import { schemas } from '@/api/generated/api'`

**State updates:** Always immutable — `jobs.value = { ...jobs.value, [id]: updated }` not `jobs.value[id] = updated`

---

## When to Stop and Ask

1. Backend endpoint missing
2. Schema conflicts with expected data
3. Breaking autosave behavior
4. Unclear layer ownership (service vs store vs composable)
5. Major architectural decision

---

## Code Quality

- **TypeScript:** Strict mode, no `any`, infer types, Zod for runtime validation
- **Vue:** Composition API only, props + emits typed, computed for derived state
- **Styling:** TailwindCSS, class-variance-authority, shadcn-vue conventions
- **Testing:** `npm run type-check` before committing

---

This is a **control file**, not documentation.
