# DocketWorks design language

The frontend design contract for new and changed screens. Use it alongside
[CLAUDE.md](../CLAUDE.md) and [ADR 0039](adr/0039-one-implementation-per-concept.md).
The owner approved this direction for PR #141 on 2026-09-06: shared defaults,
with overrides passed to the shared component or template, never a parallel implementation.

## Authority and reuse

Shared components define the default appearance and interaction. Use their variants
and props first. A necessary override belongs on the component that owns the behaviour
or layout; state its purpose in the PR. Do not copy its markup, redeclare its field
classes, or wrap it in a container that defeats its width or scrolling contract.
A recurring override becomes a shared variant, following ADR 0039.

The references are pattern-specific: [job costing](../frontend/src/features/job/costing/JobEstimateTab.tsx)
for a grid with a supporting summary, [timesheet entry](../frontend/src/features/timesheet/TimesheetEntryPage.tsx)
for compact contextual controls and keyboard entry, and [PO entry](../frontend/src/features/purchasing/PoDetailPage.tsx)
for details, lines and notes in one continuous page. The
[approved timesheet design](superpowers/specs/2026-08-10-timesheet-entry-design.md)
defines its commit and focus behaviour. v1 is a workflow comparison point, not a
source of competing components. No reference page is exempt from the breaches below.

## Page composition

- **Lists:** title and page actions, search/filter controls, then the collection and
  its count/paging controls. Use the available width for the collection.
- **Tabbed records:** identity, status and record actions above one shared tab bar.
  Switching tabs preserves the outer alignment and content gutters. A short form may
  bound its fields without narrowing or recentering the tab's entire shell.
- **Continuous entry:** compact overall details, the working grid, then supporting
  notes/history. The approved PO layout follows this order. Jobs retain their tabs;
  consistency does not require changing their information architecture to match POs.
- **Actions:** record actions belong in the record header, section actions beside
  their heading, and row actions in the row. Use clear verb labels and avoid repeating
  the same action in multiple locations without a workflow reason.
- **Supporting information:** totals stay associated with the data they summarise.
  Side panels must leave the main task usable and stack when space is insufficient.
  Notes/history remain reachable after long collections and show author and timestamp.

## Visual hierarchy

Use the Inter font stack and theme in [main.css](../frontend/src/styles/main.css).
The working interface is compact, with white/neutral surfaces, restrained borders,
and emphasis reserved for headings, actions and meaningful state.

| Role | Standard |
| --- | --- |
| Record title | 20px (`text-xl`), bold; identity and status together |
| Directory title | 24px (`text-2xl`), semibold |
| Section heading | 18px (`text-lg`), semibold |
| Working text and labels | 14px (`text-sm`); medium weight for labels |
| Metadata and table headings | 12px (`text-xs`); secondary tone, semibold table headings |
| Spacing | Existing 4px scale: 8px within control groups, 12px between a heading and content, 16px between working sections, 24px for directory/form gutters |
| Page variants | Compact entry uses 16px gutters; directories and job-tab content use 24px. All tabs in a record use the same outer variant |
| Controls | Shared button defaults: 36px regular, 32px compact, 16px icons. Grid density comes from the grid's shared controls, not independently shrinking every field |
| Surfaces | Inherit the owning component's border, radius and shadow. Use section containers for meaningful groups; do not add decorative nested cards |

The page/header variants above are the target contract; a shared page/header template
does not yet exist. Its absence is a known breach, not permission to add another local
template. Existing section and control components already have owners.

Use the shared button's dark primary treatment, outline/secondary/ghost variants for
less prominent actions, and destructive styling for destructive actions. Blue denotes
links and selected navigation through the shared navigation controls. Status colours
must accompany meaningful text or icons; do not encode state in colour alone.
Change a shared default at its owner, rather than recolouring each caller.

## Controls, editing and feedback

- Use visible field labels; placeholders are examples or hints, not labels. Icon-only
  actions need accessible names. Preserve focus indication, tab order and the shared
  tab/picker/dialog keyboard behaviour.
- Use inline editing for small contextual changes, a dialog for a bounded task, and a
  drawer for contextual work alongside the underlying record. Large multi-section
  workflows belong on a page. Use the existing overlay components and their focus handling.
- Editable grids retain their trailing draft row, stable cell identity and workflow's
  defined commit gesture. Share the mechanics; PO, job and timesheet columns and business
  validation remain domain-specific. Do not replace them with a universal configurable form.
- Distinguish autosaved edits from explicitly submitted forms. Preserve failed edits,
  expose save failures and offer a recovery action. Background refresh must not discard
  typing or remount the focused cell. Do not announce success before the operation succeeds.
- Distinguish initial loading, empty data, load failure and populated content. Retain
  usable loaded content during background refresh where possible, while exposing failures.
  Use inline validation for fields and shared error feedback for failed operations.
- Use shared currency, date, timestamp and duration formatting. Align comparable numeric
  values and totals consistently; give descriptions flexible space. Preserve readable
  notes and meaningful status labels rather than displaying internal wire values.

## Shared implementation map

| Pattern | Owner |
| --- | --- |
| Buttons and plain form fields | [Button](../frontend/src/components/ui/button.tsx), [INPUT_CLASS](../frontend/src/components/ui/field.ts) |
| Tabs and overlays | [TabBar](../frontend/src/features/shared/TabBar.tsx), [Dialog](../frontend/src/components/ui/dialog.tsx), [Drawer](../frontend/src/components/ui/drawer.tsx) |
| Working sections and statistics | [EntryGridSection](../frontend/src/features/shared/EntryGridSection.tsx), [SummaryCard](../frontend/src/features/shared/SummaryCard.tsx) |
| Editable and read-only tables | [DataTable](../frontend/src/features/shared/DataTable.tsx), [ListTable](../frontend/src/features/shared/ListTable.tsx) |
| Drafts and autosave | [useDraftRows](../frontend/src/features/shared/useDraftRows.ts), [useAutosaveField](../frontend/src/features/shared/useAutosaveField.ts) |
| Lookup and search controls | [JobPicker](../frontend/src/features/shared/JobPicker.tsx), [ItemSelect](../frontend/src/features/shared/ItemSelect.tsx), [CompanyLookup](../frontend/src/features/shared/company/CompanyLookup.tsx), [SearchInput](../frontend/src/features/shared/SearchInput.tsx) |
| Inline record editing | [InlineEditText](../frontend/src/components/InlineEditText.tsx), [InlineEditSelect](../frontend/src/components/InlineEditSelect.tsx) |
| Loading/errors and save failures | [QueryState](../frontend/src/features/shared/QueryState.tsx), [SaveFailedBadge](../frontend/src/features/shared/SaveFailedBadge.tsx) |
| Display formatting | [format.ts](../frontend/src/lib/format.ts) |

## Responsive behaviour and review

Headers wrap without hiding necessary actions. Field groups and supporting panels
stack; wide grids scroll inside their own container. The document must not overflow
horizontally. Keep every required column and action reachable, and preserve drafts,
selection and focus when resizing. Long text must not push adjacent controls off-screen.

For UI changes, the PR names the shared pattern and implementation, explains explicit
overrides, and updates affected breaches. Layout changes include actual application
Playwright screenshots and behavioural checks at 1366px desktop, 1024px tablet and
390px phone widths; include 1920px for width allocation and either side of any changed
breakpoint. Check long valid text, empty/populated/error states, keyboard entry and
resize during an edit where applicable. Verify table scrolling to the last action and
access to supporting content after long lists. Follow
[ADR 0054](adr/0054-screens-are-tested-at-production-volume.md) for production volume.

Screenshots demonstrate appearance; assertions prove behaviour. Record what was actually
checked and any gaps. Documentation and the PR checklist provide review requirements,
not a claim of automated visual enforcement. Existing gates remain unchanged; a breach
list is not a suppression baseline or a waiver of ADR 0039.

## Known breaches

Source audit on 2026-09-06, supplemented by saved job-cost and actual PO Playwright
screenshots. This is not an app-wide responsive audit. Remediation is tracked in
[rewrite-status.md](rewrite-status.md#screens); remove resolved entries here.

| Breach | Evidence and correction |
| --- | --- |
| Job tabs change outer layout | [Attachments](../frontend/src/features/job/JobAttachmentsTab.tsx) and [Settings](../frontend/src/features/job/JobSettingsTab.tsx) cap at 768px; [History](../frontend/src/features/job/JobHistoryTab.tsx) centres at 1280px and varies padding. Preserve the costing tabs' outer alignment; bound fields within it |
| Comparable collections/details use different page widths | [Staff](../frontend/src/features/admin/staff/StaffAdminPage.tsx) caps its table at 1024px; [Person details](../frontend/src/features/crm/PersonDetailPage.tsx) cap at 1152px while company details use available width. Apply the shared page contract |
| Local action styling bypasses shared buttons | [CRM people](../frontend/src/features/crm/PeopleDirectoryPage.tsx), [company details](../frontend/src/features/crm/CompanyDetailPage.tsx), [job header](../frontend/src/features/job/JobDetailPage.tsx) and [navbar](../frontend/src/features/shell/AppNavbar.tsx) hand-style actions. Call the shared button, including for button-styled links |
| Job Settings owns a second field style | [JobSettingsTab](../frontend/src/features/job/JobSettingsTab.tsx) redeclares `INPUT_CLASS`. Use the shared field owner and explicit overrides |
| Page/header and summary presentation has parallel local implementations | No common page/header template owns the variants above; [timesheet breakdown tiles](../frontend/src/features/timesheet/TimesheetEntryPage.tsx) also implement a private statistics surface alongside `SummaryCard`. Consolidate owners and express density through variants |

## Tolerated exceptions (with reasons)

These permit a specific presentation choice, not copied components or broken responsive
behaviour. Overrides still go through their shared owner; missing ownership remains debt.

| Exception | Scope and reason |
| --- | --- |
| Bounded standalone forms and dialogs | GPT: [PO creation](../frontend/src/features/purchasing/PoCreatePage.tsx) and shared dialogs contain short, focused tasks; readable field lengths matter more than filling the screen. This does not justify capping a record's line grid or recentering a tab |
| Job-cost summary sidebar | GPT: The [320px costing summary](../frontend/src/features/job/costing/JobEstimateTab.tsx) keeps totals visible alongside edits and stacks below at smaller widths. The working grid retains the remaining space |
| Compact cells and statistics | GPT: Dense repeated values need less space than standalone form fields. Express density through shared grid controls and summary variants; the private timesheet tile implementation above is still a breach |
| Spatial task layouts | GPT: [Kanban mobile columns](../frontend/src/features/kanban/KanbanMobileLayout.tsx) preserve status groups; the [workshop single-day calendar](../frontend/src/features/timesheet/WorkshopMyTimePage.tsx) bounds one person's timeline at 1024px. These task-specific bounds do not establish a width cap for office entry tables |
