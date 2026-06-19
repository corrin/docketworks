# Docketworks Design System

A **shadcn-vue** kit (new-york style, slate base) on **Tailwind v4**. The components are authored in
Vue (reka-ui primitives); this design system ships their **design language and API contracts**, not a
runnable bundle. Build on-brand UI by using the token vocabulary and idiom below, and read each
component's spec for its parts and props.

## Setup

- Load `styles.css` — it defines every token as a CSS custom property on `:root` (light) and `.dark`
  (dark), and, for Tailwind v4 pipelines, an `@theme inline` block that generates the matching utilities.
- **Dark mode** is class-based: add `class="dark"` to a root element. There is no media-query auto-switch.
- Font is **Inter** with `font-feature-settings: 'cv11','ss01'`. Default body size 15px.

## The styling idiom — Tailwind utilities bound to semantic tokens

Style with Tailwind utility classes whose color comes from **semantic tokens**, never raw hex. Every
token below exists as `bg-<token>`, `text-<token>`, and `border-<token>`:

| Token | Use for |
|---|---|
| `background` / `foreground` | page surface + default text |
| `card` / `card-foreground` | raised panels |
| `popover` / `popover-foreground` | floating surfaces (menus, popovers, tooltips) |
| `primary` / `primary-foreground` | primary actions, emphasis |
| `secondary` / `secondary-foreground` | secondary solid controls |
| `muted` / `muted-foreground` | subdued backgrounds + secondary text |
| `accent` / `accent-foreground` | hover/active surface |
| `destructive` | danger actions, errors |
| `border` / `input` / `ring` | hairlines, field borders, focus rings |
| `chart-1`..`chart-5`, `sidebar*` | data viz, app sidebar |

Pair a base with its `-foreground` (e.g. `bg-primary text-primary-foreground`). For opacity use the
slash modifier (`bg-primary/90`, `ring-ring/50`). A fixed `gray/green/yellow/red/blue/slate` hex palette
(see `tokens/colors.json`) is available for status accents only.

Radius: `rounded-sm | -md | -lg | -xl`, all derived from one `--radius` base (0.625rem). Buttons/inputs
use `rounded-md`; cards/popovers `rounded-lg`/`xl`.

### Two helpers the kit relies on
- **`cn(...)`** = `twMerge(clsx(...))` — merge/override classes safely. Every component forwards an optional
  `class` prop through `cn()`, so consumer classes win over defaults.
- **`cva`** (class-variance-authority) — declares variant→class maps. In this kit it is used sparingly:
  `Button` (`buttonVariants`), `Alert`, and `Badge` have real cva variant axes; most components have **no
  variant axis** and are styled purely by composition + `class`.

## Where the truth lives

- `styles.css` and `tokens/*.json` — the token system. Read before choosing any color/radius.
- `components/<group>/<Name>/<Name>.prompt.md` — per-component usage, parts, props, gotchas.
- `components/<group>/<Name>/<Name>.d.ts` — the typed API contract (props, variant unions, slots).

## One idiomatic snippet

```html
<!-- A card with a primary action, using only semantic tokens -->
<div class="rounded-lg border bg-card text-card-foreground shadow-sm p-6">
  <h3 class="text-sm font-semibold">Job #J-1042</h3>
  <p class="text-sm text-muted-foreground mt-1">Awaiting quote approval</p>
  <div class="mt-4 flex gap-2">
    <button class="inline-flex h-9 items-center rounded-md bg-primary px-4 text-sm
                   font-medium text-primary-foreground hover:bg-primary/90">Approve</button>
    <button class="inline-flex h-9 items-center rounded-md border bg-background px-4 text-sm
                   font-medium hover:bg-accent hover:text-accent-foreground">Dismiss</button>
  </div>
</div>
```

Available components (read the per-component specs for parts/props): Button, Input, Textarea, Label,
Checkbox, Switch, Select, Dialog, Drawer, Popover, Tooltip, DropdownMenu, Alert, Badge, Avatar, Card,
Skeleton, Progress, Sonner (toaster), LoadingState, Table, Tabs, Pagination, Collapsible, Calendar,
RangeCalendar, DatePicker, CustomDatePicker.

---

## Component index

Each component ships a typed contract (`.d.ts`), a usage reference (`.prompt.md`), and a preview card
(`.html`) under `components/<group>/<Name>/`. Most are reka-ui primitives; exceptions noted.

### Forms
- **Button** — primary action control. cva variants (default/destructive/outline/secondary/ghost/link) × sizes (default/sm/lg/icon). Polymorphic via `as`/`asChild`.
- **Input** — native text field, fixed `h-9`, `v-model`. No variants.
- **Textarea** — auto-grow native textarea (`field-sizing-content`), `min-h-16`. No variants.
- **Label** — reka-ui label, disabled-aware via peer/group. No variants.
- **Checkbox** — reka-ui, tri-state (`boolean | 'indeterminate'`). No variants.
- **Switch** — reka-ui toggle, optional `thumb` slot. No variants.
- **Select** — 11 parts (Trigger/Value/Content/Group/Label/Item/Separator/scroll buttons). Trigger size axis (`default`/`sm`).

### Overlays
- **Dialog** — modal; parts incl. Content, ScrollContent, Header/Footer/Title/Description, Close. Content auto-portals + ships its X.
- **Drawer** — **vaul-vue** (not reka-ui); placement via root `direction` (default bottom); `shouldScaleBackground` default true.
- **Popover** — Trigger/Anchor/Content; Content `align='center'`, `sideOffset=4`.
- **Tooltip** — Provider/Trigger/Content; `delayDuration` default **0**, built-in arrow.
- **DropdownMenu** — full menu set incl. Checkbox/Radio items, Sub-menus, Shortcut. Item `variant` default/destructive + `inset`.

### Display
- **Alert** — cva variant default/destructive; leading svg auto-positioned.
- **Badge** — cva variant default/secondary/destructive/outline; polymorphic.
- **Avatar** — Avatar/AvatarImage/AvatarFallback; size via `class` (default `size-8`).
- **Card** — Card + Header/Title/Description/Action/Content/Footer. Horizontal padding lives on inner parts.
- **Skeleton** — pulse placeholder, sized via `class`.
- **Progress** — reka-ui, `modelValue` 0–100, determinate.
- **Sonner** — `Toaster` host wrapping vue-sonner; `toast()` imported directly from `vue-sonner` (not re-exported).
- **LoadingState** — bespoke tri-state (loading/empty/content) wrapper; slots default/empty-icon/empty-actions. Uses some hard-coded grays (not tokens).

### Data & Navigation
- **Table** — native table elements; 9 parts incl. TableEmpty (`colspan`). Selected-row styling via `data-[state=selected]`. `valueUpdater` helper for @tanstack/vue-table.
- **Tabs** — reka-ui; List/Trigger/Content; `v-model`, `orientation`, `activationMode`.
- **Pagination** — custom (not reka-ui): ghost Buttons + chevrons, windowed (max 10), `page`/`total`, emits `update:page`.
- **Collapsible** — custom provide/inject; Collapsible + CollapsibleContent; **no Trigger part** (wire your own); `v-model:open`.

### Date & Time
- **Calendar** — reka-ui CalendarRoot; 12 parts (Header/Heading/Prev/Next, Grid*, HeadCell, Cell, CellTrigger). v-model `DateValue` (`@internationalized/date`).
- **RangeCalendar** — reka-ui RangeCalendarRoot; mirrors Calendar; v-model range `{ start, end }`.
- **DatePicker** — composed Button + Popover + Calendar; v-model ISO string `'YYYY-MM-DD' | null` (`en-NZ` formatting).
- **CustomDatePicker** — two native `<input type="date">`; v-model `DateRange { from?, to? }` ISO strings. Not a calendar.

> **Note on rendering:** these are Vue components. Claude Design renders React, so no runnable component
> bundle is shipped — use the tokens + idiom above to build on-brand, and the per-component specs for API shape.
