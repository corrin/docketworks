# design-sync notes

## This is a manual, off-script extraction
The repo (`frontend/`) is a **private application**, not a publishable component library — there is no
library `dist/`, no Storybook, and the components are **Vue** (reka-ui). Claude Design renders **React**,
so the standard converter (`package-build.mjs`) does not apply. Per user direction, we do NOT build an
isolated Vite lib and do NOT stub-and-render-verify (couplings in `ui/` are minimal: Pinia is cache-only,
all API access via the generated OpenAPI client).

**Deliverable = framework-agnostic only:** `styles.css` + `tokens/`, per-component `.d.ts` + `.prompt.md`
+ a self-contained preview `.html` card, and a `conventions.md` header. **No `_ds_bundle.js`.**

## Source of truth
- Tokens: `frontend/src/assets/main.css` (`@theme inline` + `:root` + `.dark`, oklch).
- Components: `frontend/src/components/ui/<group>/` — 28 groups (one standalone `LoadingState.vue`).
- `cn()` = `frontend/src/lib/utils.ts`; cva only in `button`, `alert`, `badge`.

## Re-sync procedure (manual)
Re-run the extraction by re-reading `frontend/src/components/ui/` and rebuilding `.design-sync/ds-bundle/`.
There is **no `_ds_sync.json` anchor** (the converter's hashing recipe doesn't fit this layout), so a
re-sync re-extracts everything — correct for this flow. The build dir is regenerable; not committed.

## Gotchas found during extraction
- `LoadingState` uses hard-coded grays/blue, not design tokens.
- `Drawer` is vaul-vue, not reka-ui. `Pagination` and `Collapsible` are custom (no upstream parts;
  Collapsible has no Trigger part).
- `Sonner` re-exports only `Toaster`; `toast()` comes straight from `vue-sonner`.
- `sonner` group's component dir is named `Sonner` (PascalCase of the group), though the export is `Toaster`.
