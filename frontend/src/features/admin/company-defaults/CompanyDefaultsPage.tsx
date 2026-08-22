import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  companyDefaultsPartialUpdateMutation,
  companyDefaultsRetrieveQueryKey,
  companyDefaultsSchemaRetrieveOptions,
  type CompanyDefaultsOut,
  type SettingsFieldOut,
  type SettingsSectionOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { QueryState } from '@/features/shared/QueryState'
import { useUnsavedChangesGuard } from '@/features/shared/useUnsavedChangesGuard'
import { companyDefaultsQueryOptions } from '@/features/shell'

import { SettingsFieldInput } from './SettingsFieldInput'
import {
  buildPatch,
  dirtyKeys,
  imageUrlKey,
  snapshotSection,
  type CompanyDefaultsRecord,
  type FieldValue,
  type SectionSnapshot,
} from './snapshot'

/** The working week the timesheet screens bill against; ported from v1
 *  SectionForm.vue:725-731. Saturday and Sunday have no hours columns —
 *  weekend work is enabled by `weekend_timesheets_enabled`, not by a span. */
const WORKING_DAYS: readonly { label: string; startKey: string; endKey: string }[] = [
  { label: 'Monday', startKey: 'mon_start', endKey: 'mon_end' },
  { label: 'Tuesday', startKey: 'tue_start', endKey: 'tue_end' },
  { label: 'Wednesday', startKey: 'wed_start', endKey: 'wed_end' },
  { label: 'Thursday', startKey: 'thu_start', endKey: 'thu_end' },
  { label: 'Friday', startKey: 'fri_start', endKey: 'fri_end' },
]

const WORKING_HOURS_TIME_KEYS = new Set(WORKING_DAYS.flatMap((day) => [day.startKey, day.endKey]))

export function CompanyDefaultsPage({ section }: { section: string }) {
  // Opus: The shell owns this singleton's options (5-minute staleTime, preloaded for
  // every authenticated page); a second useQuery over the raw generated options
  // would be a sibling cache entry that the save path's setQueryData never
  // reaches, and TimesheetEntryPage already reads it this way.
  const defaultsQuery = useQuery(companyDefaultsQueryOptions())
  const schemaQuery = useQuery(companyDefaultsSchemaRetrieveOptions())

  return (
    <div
      className="mx-auto flex max-w-5xl flex-col gap-6 p-6"
      data-automation-id="CompanyDefaultsPage-root"
    >
      <h1 className="text-2xl font-semibold">Company Defaults</h1>
      <QueryState
        isPending={defaultsQuery.isPending || schemaQuery.isPending}
        isError={defaultsQuery.isError || schemaQuery.isError}
        loadingNode={<p className="text-sm text-slate-500">Loading company defaults…</p>}
        errorNode={<p className="text-sm text-red-700">Could not load company defaults.</p>}
      >
        {defaultsQuery.data && schemaQuery.data && (
          <SectionShell
            sections={schemaQuery.data.sections}
            sectionKey={section}
            defaults={defaultsQuery.data}
          />
        )}
      </QueryState>
    </div>
  )
}

function SectionShell({
  sections,
  sectionKey,
  defaults,
}: {
  sections: SettingsSectionOut[]
  sectionKey: string
  defaults: CompanyDefaultsOut
}) {
  const current = sections.find((candidate) => candidate.key === sectionKey)
  return (
    <>
      <nav
        aria-label="Settings sections"
        className="flex flex-wrap gap-1 border-b border-slate-200"
        data-automation-id="CompanyDefaultsPage-section-nav"
      >
        {sections.map((candidate) => (
          <Link
            key={candidate.key}
            to="/admin/company-defaults/$section"
            params={{ section: candidate.key }}
            className="rounded-t-md px-3 py-2 text-sm font-medium text-slate-600 hover:bg-slate-100"
            activeProps={{
              className:
                'rounded-t-md px-3 py-2 text-sm font-medium border-b-2 border-slate-800 text-slate-900',
            }}
            data-automation-id={`CompanyDefaultsPage-section-link-${candidate.key}`}
          >
            {candidate.title}
          </Link>
        ))}
      </nav>
      {current ? (
        // key= remounts the form per section so snapshots re-seed; the blocker
        // below still guards the navigation that causes the remount.
        <SectionForm key={current.key} section={current} defaults={defaults} />
      ) : (
        <p className="py-16 text-center text-sm text-slate-500">
          Unknown section: <code>{sectionKey}</code>
        </p>
      )}
    </>
  )
}

/** An image field's live preview: the `${key}_url` companion straight from the
 * shell-owned company-defaults query, not the mounted drafts/server snapshot.
 * The upload/remove mutations setQueryData the fresh row on the same cache
 * entry `defaults` is read from, so this stays current without a remount —
 * where the snapshot only refreshes on the next SectionForm mount. */
function imageUrl(defaults: CompanyDefaultsRecord, key: string): FieldValue {
  const raw = defaults[imageUrlKey(key)]
  return typeof raw === 'string' ? raw : null
}

/** The ten working-hours keys are model fields the schema endpoint always
 *  emits, so a missing one is a registry defect rather than a case to lay out
 *  around (ADR 0015; apps/core/tests/test_company_defaults_schema_api.py holds
 *  the section membership). */
function requireField(fields: Map<string, SettingsFieldOut>, key: string): SettingsFieldOut {
  const field = fields.get(key)
  if (field === undefined) {
    throw new Error(`The working hours section is missing the ${key} field.`)
  }
  return field
}

function SectionForm({
  section,
  defaults,
}: {
  section: SettingsSectionOut
  defaults: CompanyDefaultsOut
}) {
  const queryClient = useQueryClient()
  const updateMutation = useMutation(companyDefaultsPartialUpdateMutation())
  // Two snapshots, seeded ONCE and advanced together only on a successful save:
  // no effect re-hydrates them, so a background refetch cannot wipe what the
  // admin has typed (the bug LeaveSettingsPage.tsx:141-148 records).
  const [server, setServer] = useState<SectionSnapshot>(() =>
    snapshotSection(defaults, section.fields),
  )
  const [drafts, setDrafts] = useState<SectionSnapshot>(() =>
    snapshotSection(defaults, section.fields),
  )
  const [saving, setSaving] = useState(false)

  const dirty = useMemo(
    () => dirtyKeys(section.fields, drafts, server),
    [section.fields, drafts, server],
  )
  const isDirty = dirty.length > 0

  useUnsavedChangesGuard(isDirty)

  const setDraft = (key: string, value: FieldValue): void => {
    setDrafts((previous) => ({ ...previous, [key]: value }))
  }

  async function save(): Promise<void> {
    if (saving) return
    setSaving(true)
    try {
      const fresh = await updateMutation.mutateAsync({
        body: buildPatch(section.fields, drafts, server),
      })
      // Company defaults is app-shell boot data (features/shell preloads it with
      // a 5-minute staleTime): setQueryData from the PATCH response, or every
      // other consumer keeps stale defaults for five minutes.
      queryClient.setQueryData(companyDefaultsRetrieveQueryKey(), fresh)
      setServer(snapshotSection(fresh, section.fields))
      setDrafts(snapshotSection(fresh, section.fields))
      toast.success(`${section.title} saved`)
    } catch (error) {
      toast.error(apiErrorMessage(error, `Could not save ${section.title}.`))
    } finally {
      setSaving(false)
    }
  }

  const isWorkingHours = section.key === 'working_hours'
  const fieldsByKey = new Map(section.fields.map((field) => [field.key, field]))
  // The day grid draws the ten time fields itself, so the generic grid above it
  // renders only what is left (weekend timesheets, efficiency factor).
  const genericFields = isWorkingHours
    ? section.fields.filter((field) => !WORKING_HOURS_TIME_KEYS.has(field.key))
    : section.fields

  return (
    <div className="flex flex-col gap-6">
      <div className="grid grid-cols-1 gap-x-6 gap-y-4 md:grid-cols-2">
        {genericFields.map((field) => {
          const value =
            field.type === 'image' ? imageUrl(defaults, field.key) : (drafts[field.key] ?? null)
          const content = (
            <>
              <span className="text-slate-700">{field.label}</span>
              <SettingsFieldInput
                field={field}
                section={section.key}
                value={value}
                onChange={(next) => setDraft(field.key, next)}
              />
              {field.help_text && (
                <span className="text-xs font-normal text-slate-500">{field.help_text}</span>
              )}
            </>
          )
          // Opus: LogoField's own upload control is a <label>-wrapped file input;
          // nesting that inside this field's caption <label> is invalid HTML
          // and makes the OUTER label's implicit control resolve to the
          // hidden file input, so clicking the caption or the preview image
          // opens the file picker (a hang under Playwright). image fields get
          // a <div> caption instead — every other widget type keeps <label>.
          return field.type === 'image' ? (
            <div key={field.key} className="flex flex-col gap-1 text-sm font-medium">
              {content}
            </div>
          ) : (
            <label key={field.key} className="flex flex-col gap-1 text-sm font-medium">
              {content}
            </label>
          )
        })}
      </div>
      {isWorkingHours && (
        <div className="flex flex-col gap-3" data-automation-id="CompanyDefaultsPage-working-days">
          {WORKING_DAYS.map((day) => (
            <div
              key={day.startKey}
              className="flex flex-col gap-2 rounded-md border border-slate-200 p-3 sm:flex-row sm:items-center sm:gap-4"
            >
              <span className="text-sm font-medium text-slate-700 sm:w-28">{day.label}</span>
              <div className="flex flex-1 gap-2">
                {(
                  [
                    ['Start', day.startKey],
                    ['End', day.endKey],
                  ] as const
                ).map(([boundary, key]) => {
                  const field = requireField(fieldsByKey, key)
                  return (
                    <label key={key} className="flex flex-1 flex-col gap-1">
                      <span className="text-xs text-slate-500">{boundary}</span>
                      <SettingsFieldInput
                        field={field}
                        section={section.key}
                        value={drafts[key] ?? null}
                        onChange={(value) => setDraft(key, value)}
                      />
                    </label>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}
      <div
        className="sticky bottom-0 flex justify-end gap-2 border-t border-slate-200 bg-white/95 py-3"
        data-automation-id="CompanyDefaultsPage-footer"
      >
        <Button
          variant="outline"
          disabled={saving || !isDirty}
          onClick={() => setDrafts(server)}
          data-automation-id="CompanyDefaultsPage-cancel-button"
        >
          Cancel
        </Button>
        <Button
          disabled={saving || !isDirty}
          onClick={() => void save()}
          data-automation-id="CompanyDefaultsPage-save-button"
        >
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </div>
    </div>
  )
}
