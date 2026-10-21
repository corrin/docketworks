import { useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Trans, useTranslation } from 'react-i18next'
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
const WORKING_DAYS = [
  { day: 'monday', startKey: 'mon_start', endKey: 'mon_end' },
  { day: 'tuesday', startKey: 'tue_start', endKey: 'tue_end' },
  { day: 'wednesday', startKey: 'wed_start', endKey: 'wed_end' },
  { day: 'thursday', startKey: 'thu_start', endKey: 'thu_end' },
  { day: 'friday', startKey: 'fri_start', endKey: 'fri_end' },
] as const

const WORKING_HOURS_TIME_KEYS = new Set<string>(
  WORKING_DAYS.flatMap((day) => [day.startKey, day.endKey]),
)

// Carried by the save but never drawn: google_place_id has to be a section
// field so buildPatch sends it, and the address picker is the only thing that
// sets it. Filtered here rather than by returning null from the control,
// because the caption <span> below is rendered by this grid — a hidden control
// alone leaves a labelled empty cell reading "Google Place Id".
const UNDRAWN_KEYS = new Set(['google_place_id'])

export function CompanyDefaultsPage({ section }: { section: string }) {
  // Opus: The shell owns this singleton's options (5-minute staleTime, preloaded for
  // every authenticated page); a second useQuery over the raw generated options
  // would be a sibling cache entry that the save path's setQueryData never
  // reaches, and TimesheetEntryPage already reads it this way.
  const { t } = useTranslation('admin')
  const defaultsQuery = useQuery(companyDefaultsQueryOptions())
  const schemaQuery = useQuery(companyDefaultsSchemaRetrieveOptions())

  return (
    <div
      className="mx-auto flex max-w-5xl flex-col gap-6 p-6"
      data-automation-id="CompanyDefaultsPage-root"
    >
      <h1 className="text-2xl font-semibold">{t('companyDefaults.title')}</h1>
      <QueryState
        isPending={defaultsQuery.isPending || schemaQuery.isPending}
        isError={defaultsQuery.isError || schemaQuery.isError}
        loadingNode={<p className="text-sm text-slate-500">{t('companyDefaults.loading')}</p>}
        errorNode={<p className="text-sm text-red-700">{t('companyDefaults.loadFailed')}</p>}
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
  const { t } = useTranslation('admin')
  const current = sections.find((candidate) => candidate.key === sectionKey)
  return (
    <>
      <nav
        aria-label={t('companyDefaults.sectionsNav')}
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
          <Trans
            t={t}
            i18nKey="companyDefaults.unknownSection"
            values={{ section: sectionKey }}
            components={{ code: <code /> }}
          />
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
  const { t } = useTranslation('admin')
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

  const applyDrafts = (values: Record<string, FieldValue>): void => {
    setDrafts((previous) => ({ ...previous, ...values }))
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
      toast.success(t('companyDefaults.saved', { section: section.title }))
    } catch (error) {
      toast.error(
        apiErrorMessage(error, t('companyDefaults.saveFailed', { section: section.title })),
      )
    } finally {
      setSaving(false)
    }
  }

  const isWorkingHours = section.key === 'working_hours'
  const fieldsByKey = new Map(section.fields.map((field) => [field.key, field]))
  // The day grid draws the ten time fields itself, so the generic grid above it
  // renders only what is left (weekend timesheets, efficiency factor).
  const drawableFields = section.fields.filter((field) => !UNDRAWN_KEYS.has(field.key))
  const genericFields = isWorkingHours
    ? drawableFields.filter((field) => !WORKING_HOURS_TIME_KEYS.has(field.key))
    : drawableFields

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
                onApplyMany={applyDrafts}
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
              <span className="text-sm font-medium text-slate-700 sm:w-28">
                {t(`companyDefaults.days.${day.day}`)}
              </span>
              <div className="flex flex-1 gap-2">
                {(
                  [
                    [t('companyDefaults.start'), day.startKey],
                    [t('companyDefaults.end'), day.endKey],
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
                        onApplyMany={applyDrafts}
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
          {t('companyDefaults.cancel')}
        </Button>
        <Button
          disabled={saving || !isDirty}
          onClick={() => void save()}
          data-automation-id="CompanyDefaultsPage-save-button"
        >
          {saving ? t('companyDefaults.saving') : t('companyDefaults.save')}
        </Button>
      </div>
    </div>
  )
}
