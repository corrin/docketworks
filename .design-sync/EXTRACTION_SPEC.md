# Extraction spec for design-sync subagents

You extract a **framework-agnostic** spec of shadcn-vue components for upload to claude.ai/design.
The design tool renders React, so we DO NOT ship runnable component code — only contracts, docs, and a
discoverable preview card. Everything you write must be derived by **reading** the real source under
`/home/corrin/src/docketworks/frontend/src/components/ui/<group>/` (the `.vue` files + `index.ts`).
Do not invent props, variants, or parts — read them from `defineProps`, the cva config in `index.ts`,
and the reka-ui primitive each part wraps.

## For each assigned group, write THREE files

Output dir: `/home/corrin/src/docketworks/.design-sync/ds-bundle/components/<group>/<Name>/`
where `<Name>` is the PascalCase group name (e.g. `dropdown-menu` -> `DropdownMenu`, `button` -> `Button`).

### 1. `<Name>.d.ts` — the API contract
- A TypeScript declaration for the component (and every exported sub-component/part).
- Export a `<Name>Props` interface (and per-part `XProps` interfaces) with the REAL prop names and types
  read from each `.vue`'s `defineProps`/`withDefaults`. Resolve cva `VariantProps` into literal unions
  (e.g. `variant?: 'default' | 'destructive' | 'outline' | 'secondary' | 'ghost' | 'link'`).
- Include `class?: string` where the component forwards a class via `cn()`.
- Note slots in a JSDoc comment per component (`@slot default`, named slots if any).
- Re-export the cva helper type if one exists (e.g. `export type ButtonVariants = ...`).
- Keep it pure declarations — no implementation.

### 2. `<Name>.prompt.md` — usage reference for the design agent
Sections, terse and concrete:
- **`# <Name>`** one-line description + when to use it.
- **Parts** — bullet list of the exported components from `index.ts` and what each is for.
- **Props** — the key props/variants/sizes with their literal values and defaults (from `defaultVariants`).
- **Usage** — ONE minimal composition example using the REAL import (`import { ... } from '@/components/ui/<group>'`)
  and the REAL component/part names and slot structure. Vue SFC `<template>` snippet is fine — it documents
  composition; the agent translates intent, not literal code.
- **Notes** — gotchas: which reka-ui primitive backs it, controlled-vs-uncontrolled (`v-model`), required wrappers
  (e.g. Trigger must be inside Root), accessibility behaviors. Only what you can verify from source.

### 3. `<Name>.html` — discoverable preview card
- **First line MUST be exactly:** `<!-- @dsCard group="<Group>" -->` where `<Group>` is the category you were
  assigned (e.g. `Forms`, `Overlays`, `Display`, `Data & Navigation`, `Date & Time`).
- A self-contained HTML fragment that renders a faithful static preview using the **real design tokens**.
  Paste the token `:root` block below into a `<style>` so the card renders standalone (do NOT rely on an
  external stylesheet being injected). Use the token CSS variables (`var(--primary)`, `var(--radius)`, etc.)
  and the component's real geometry (heights/padding read from the cva size classes) so the preview looks right.
- Show the component title, its main variants/sizes, and a representative instance. Keep it compact
  (a card ~360px wide). This is a human-facing picker thumbnail, not a functional component.

## Token `:root` block to embed in every card's `<style>`

```css
:root{
  --background:oklch(1 0 0);--foreground:oklch(0.129 0.042 264.695);
  --card:oklch(1 0 0);--card-foreground:oklch(0.129 0.042 264.695);
  --popover:oklch(1 0 0);--popover-foreground:oklch(0.129 0.042 264.695);
  --primary:oklch(0.208 0.042 265.755);--primary-foreground:oklch(0.984 0.003 247.858);
  --secondary:oklch(0.968 0.007 247.896);--secondary-foreground:oklch(0.208 0.042 265.755);
  --muted:oklch(0.968 0.007 247.896);--muted-foreground:oklch(0.554 0.046 257.417);
  --accent:oklch(0.968 0.007 247.896);--accent-foreground:oklch(0.208 0.042 265.755);
  --destructive:oklch(0.577 0.245 27.325);--destructive-foreground:oklch(0.577 0.245 27.325);
  --border:oklch(0.929 0.013 255.508);--input:oklch(0.929 0.013 255.508);--ring:oklch(0.704 0.04 256.788);
  --radius:0.625rem;
  font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
}
```

Radius scale: `--radius-sm: calc(var(--radius) - 4px)`, `-md: calc(var(--radius) - 2px)`, `-lg: var(--radius)`,
`-xl: calc(var(--radius) + 4px)`. Default control height is `h-9` (2.25rem); sm `h-8`; lg `h-10`.

## Rules
- Read before you write. Never guess a prop or variant — open the file.
- shadcn-vue groups bundle parts (Root/Trigger/Content/etc.). Document the GROUP as one component with parts.
- If a group has no variants (e.g. `input`), say so; don't fabricate a variant axis.
- Do not edit anything under `frontend/`. Write only under `.design-sync/ds-bundle/`.
- Report back: a one-line-per-group summary of parts + variants found, and any anomaly. Keep file CONTENT out
  of your reply — you wrote it to disk; just summarize.
