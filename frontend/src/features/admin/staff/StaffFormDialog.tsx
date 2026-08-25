import { useEffect, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  accountsStaffCreateMutation,
  accountsStaffIconCreateMutation,
  accountsStaffListQueryKey,
  accountsStaffPartialUpdateMutation,
  apiErrorMessage,
  type StaffCreateIn,
  type StaffListItemOut,
  type StaffUpdateIn,
} from '@/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { INPUT_CLASS } from '@/components/ui/field'
import { localIsoDate } from '@/lib/format'

// Mirrors apps/core/uploads.py's ALLOWED_IMAGE_SUFFIXES (png/jpg/jpeg/gif/
// webp, no svg) — the server PIL-verifies too; this keeps the picker from
// offering a format the server will refuse.
const ICON_ACCEPT = 'image/png,image/jpeg,image/gif,image/webp'

const HOUR_KEYS = [
  ['hours_mon', 'Mon'],
  ['hours_tue', 'Tue'],
  ['hours_wed', 'Wed'],
  ['hours_thu', 'Thu'],
  ['hours_fri', 'Fri'],
  ['hours_sat', 'Sat'],
  ['hours_sun', 'Sun'],
] as const

type HourKey = (typeof HOUR_KEYS)[number][0]

const FLAG_KEYS = [
  'is_office_staff',
  'is_workshop_staff',
  'is_superuser',
  'is_staff_manager',
] as const
type FlagKey = (typeof FLAG_KEYS)[number]

type PayBasis = '' | 'hourly' | 'salary'

/** The select's options are exactly this union; anything else is a markup
 * defect, so fail early rather than cast (ADR 0028). */
function requirePayBasis(value: string): PayBasis {
  if (value === '' || value === 'hourly' || value === 'salary') return value
  throw new Error(`Unexpected pay basis option "${value}".`)
}

/** Same fail-early rule on the wire value: the model's choices restrict it,
 * so anything else is a data defect to surface, never to coerce to "" and
 * then silently null out on the next unrelated save. */
function payBasisFromWire(value: string | null): PayBasis {
  if (value === null) return ''
  return requirePayBasis(value)
}

interface Drafts {
  first_name: string
  last_name: string
  preferred_name: string
  office_email: string
  payroll_email: string
  password: string
  password_confirm: string
  base_wage_rate: string
  xero_user_id: string
  employment_start_date: string
  date_left: string
  pay_basis: PayBasis
  hours: Record<HourKey, string>
  flags: Record<FlagKey, boolean>
}

function snapshot(staff: StaffListItemOut | null): Drafts {
  return {
    first_name: staff?.first_name ?? '',
    last_name: staff?.last_name ?? '',
    preferred_name: staff?.preferred_name ?? '',
    office_email: staff?.office_email ?? '',
    payroll_email: staff?.payroll_email ?? '',
    password: '',
    password_confirm: '',
    base_wage_rate: staff ? String(staff.base_wage_rate) : '0',
    xero_user_id: staff?.xero_user_id ?? '',
    employment_start_date: staff?.employment_start_date ?? localIsoDate(),
    date_left: staff?.date_left ?? '',
    pay_basis: staff ? payBasisFromWire(staff.pay_basis) : '',
    hours: {
      hours_mon: staff ? String(staff.hours_mon) : '8',
      hours_tue: staff ? String(staff.hours_tue) : '8',
      hours_wed: staff ? String(staff.hours_wed) : '8',
      hours_thu: staff ? String(staff.hours_thu) : '8',
      hours_fri: staff ? String(staff.hours_fri) : '8',
      hours_sat: staff ? String(staff.hours_sat) : '0',
      hours_sun: staff ? String(staff.hours_sun) : '0',
    },
    flags: {
      is_office_staff: staff?.is_office_staff ?? false,
      is_workshop_staff: staff?.is_workshop_staff ?? true,
      is_superuser: staff?.is_superuser ?? false,
      is_staff_manager: staff?.is_staff_manager ?? false,
    },
  }
}

/** '' means unset for the nullable text columns (ADR 0040: null clears, blank
 * is a 422 — so an emptied box must become null on the wire, never ""). */
const textOrNull = (value: string): string | null => {
  const trimmed = value.trim()
  return trimmed === '' ? null : trimmed
}

function buildCreateBody(drafts: Drafts): StaffCreateIn {
  const body: StaffCreateIn = {
    first_name: drafts.first_name.trim(),
    last_name: drafts.last_name.trim(),
    office_email: drafts.office_email.trim(),
    password: drafts.password,
    base_wage_rate: Number(drafts.base_wage_rate),
    employment_start_date: drafts.employment_start_date,
    ...drafts.flags,
  }
  const preferred = textOrNull(drafts.preferred_name)
  if (preferred !== null) body.preferred_name = preferred
  const payroll = textOrNull(drafts.payroll_email)
  if (payroll !== null) body.payroll_email = payroll
  const xero = textOrNull(drafts.xero_user_id)
  if (xero !== null) body.xero_user_id = xero
  if (drafts.date_left !== '') body.date_left = drafts.date_left
  if (drafts.pay_basis !== '') body.pay_basis = drafts.pay_basis
  for (const [key] of HOUR_KEYS) {
    body[key] = Number(drafts.hours[key])
  }
  return body
}

/** Dirty fields only — exclude_unset is the wire contract, so an untouched
 * field must not appear at all. */
function buildPatch(drafts: Drafts, staff: StaffListItemOut): StaffUpdateIn {
  const patch: StaffUpdateIn = {}
  if (drafts.first_name.trim() !== staff.first_name) patch.first_name = drafts.first_name.trim()
  if (drafts.last_name.trim() !== staff.last_name) patch.last_name = drafts.last_name.trim()
  if (drafts.office_email.trim() !== staff.office_email) {
    patch.office_email = drafts.office_email.trim()
  }
  if (textOrNull(drafts.preferred_name) !== staff.preferred_name) {
    patch.preferred_name = textOrNull(drafts.preferred_name)
  }
  if (textOrNull(drafts.payroll_email) !== staff.payroll_email) {
    patch.payroll_email = textOrNull(drafts.payroll_email)
  }
  if (textOrNull(drafts.xero_user_id) !== staff.xero_user_id) {
    patch.xero_user_id = textOrNull(drafts.xero_user_id)
  }
  if (drafts.password !== '') patch.password = drafts.password
  if (Number(drafts.base_wage_rate) !== staff.base_wage_rate) {
    patch.base_wage_rate = Number(drafts.base_wage_rate)
  }
  if (drafts.employment_start_date !== staff.employment_start_date) {
    patch.employment_start_date = drafts.employment_start_date
  }
  if ((drafts.date_left || null) !== staff.date_left) patch.date_left = drafts.date_left || null
  if ((drafts.pay_basis || null) !== staff.pay_basis) patch.pay_basis = drafts.pay_basis || null
  for (const [key] of HOUR_KEYS) {
    if (Number(drafts.hours[key]) !== staff[key]) {
      patch[key] = Number(drafts.hours[key])
    }
  }
  for (const key of FLAG_KEYS) {
    if (drafts.flags[key] !== staff[key]) patch[key] = drafts.flags[key]
  }
  return patch
}

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  /** null = create a new staff member. */
  staff: StaffListItemOut | null
}

/**
 * Create/edit modal for the staff admin page. The icon is staged, not
 * uploaded on pick: multipart cannot share a body with the JSON write, so the
 * save is two-phase (JSON first, then the icon), and a failed second phase
 * reports "saved, but the photo could not be uploaded" rather than failing
 * the save — the row exists either way.
 */
export function StaffFormDialog({ open, onOpenChange, staff }: Props) {
  const queryClient = useQueryClient()
  const createMutation = useMutation(accountsStaffCreateMutation())
  const updateMutation = useMutation(accountsStaffPartialUpdateMutation())
  const iconMutation = useMutation(accountsStaffIconCreateMutation())
  const [drafts, setDrafts] = useState<Drafts>(() => snapshot(staff))
  const [iconFile, setIconFile] = useState<File | null>(null)
  const [iconPreview, setIconPreview] = useState<string | null>(null)
  const [validationError, setValidationError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!open) return
    setDrafts(snapshot(staff))
    setIconFile(null)
    setValidationError(null)
  }, [open, staff])

  // An object URL must be revoked or every staged pick leaks a blob.
  useEffect(() => {
    if (!iconFile) {
      setIconPreview(null)
      return undefined
    }
    const url = URL.createObjectURL(iconFile)
    setIconPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [iconFile])

  const setDraft = <K extends keyof Drafts>(key: K, value: Drafts[K]): void => {
    setDrafts((previous) => ({ ...previous, [key]: value }))
  }

  const setRows = (updater: (rows: StaffListItemOut[]) => StaffListItemOut[]): void => {
    queryClient.setQueryData(accountsStaffListQueryKey(), (rows?: StaffListItemOut[]) =>
      rows === undefined ? rows : updater(rows),
    )
  }

  function localProblem(): string | null {
    if (drafts.first_name.trim() === '' || drafts.last_name.trim() === '') {
      return 'First and last name are required.'
    }
    if (drafts.office_email.trim() === '') return 'Office email is required.'
    if (staff === null && drafts.password === '') return 'A password is required.'
    if (drafts.password !== drafts.password_confirm) return 'The passwords do not match.'
    // An emptied number box must be an error, never a silent 0 — zeroing
    // base_wage_rate is a payroll change nobody asked for.
    if (drafts.base_wage_rate === '' || Number.isNaN(Number(drafts.base_wage_rate))) {
      return 'A base wage rate is required.'
    }
    // min={0} on the input does not stop a typed negative: there is no <form>
    // submission here to trigger native constraint validation.
    if (Number(drafts.base_wage_rate) < 0) return 'The base wage rate cannot be negative.'
    for (const [key, label] of HOUR_KEYS) {
      if (drafts.hours[key] === '' || Number.isNaN(Number(drafts.hours[key]))) {
        return `Working hours are required for ${label} (0 for a non-working day).`
      }
      if (Number(drafts.hours[key]) < 0) {
        return `Working hours for ${label} cannot be negative.`
      }
    }
    if (drafts.employment_start_date === '') return 'An employment start date is required.'
    return null
  }

  async function save(): Promise<void> {
    if (saving) return
    const problem = localProblem()
    if (problem) {
      setValidationError(problem)
      return
    }
    setValidationError(null)
    setSaving(true)
    try {
      let fresh: StaffListItemOut
      if (staff === null) {
        fresh = await createMutation.mutateAsync({ body: buildCreateBody(drafts) })
        setRows((rows) => [...rows, fresh])
      } else {
        const patch = buildPatch(drafts, staff)
        if (Object.keys(patch).length > 0) {
          fresh = await updateMutation.mutateAsync({
            path: { staff_id: staff.id },
            body: patch,
          })
        } else {
          fresh = staff
        }
        setRows((rows) => rows.map((row) => (row.id === fresh.id ? fresh : row)))
      }
      if (iconFile) {
        try {
          const withIcon = await iconMutation.mutateAsync({
            path: { staff_id: fresh.id },
            body: { file: iconFile },
          })
          setRows((rows) => rows.map((row) => (row.id === withIcon.id ? withIcon : row)))
        } catch (error) {
          // The row is saved; only the photo failed. Report exactly that and
          // close anyway — re-opening the modal retries just the photo.
          toast.error(
            apiErrorMessage(error, 'Staff member saved, but the photo could not be uploaded.'),
          )
          onOpenChange(false)
          return
        }
      }
      toast.success('Staff member saved successfully')
      onOpenChange(false)
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Could not save the staff member.'))
    } finally {
      setSaving(false)
    }
  }

  const iconUrl = iconPreview ?? staff?.icon_url ?? null

  return (
    // While a save is in flight the dialog must not dismiss (Esc/outside
    // click) — a completion landing after a re-open would close the wrong
    // dialog and toast out of context.
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!saving) onOpenChange(next)
      }}
    >
      <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>{staff === null ? 'New Staff' : 'Edit Staff'}</DialogTitle>
        </DialogHeader>

        <div className="flex flex-col gap-6">
          <FormSection title="Personal">
            <div className="grid grid-cols-1 gap-x-6 gap-y-4 md:grid-cols-2">
              <TextField
                label="First name"
                automationId="StaffFormDialog-first-name"
                value={drafts.first_name}
                onChange={(value) => setDraft('first_name', value)}
              />
              <TextField
                label="Last name"
                automationId="StaffFormDialog-last-name"
                value={drafts.last_name}
                onChange={(value) => setDraft('last_name', value)}
              />
              <TextField
                label="Preferred name"
                automationId="StaffFormDialog-preferred-name"
                value={drafts.preferred_name}
                onChange={(value) => setDraft('preferred_name', value)}
              />
              <TextField
                label="Office email"
                type="email"
                automationId="StaffFormDialog-email"
                value={drafts.office_email}
                onChange={(value) => setDraft('office_email', value)}
              />
              <TextField
                label="Payroll email"
                type="email"
                automationId="StaffFormDialog-payroll-email"
                value={drafts.payroll_email}
                onChange={(value) => setDraft('payroll_email', value)}
              />
              <TextField
                label="Xero user id"
                automationId="StaffFormDialog-xero-user-id"
                value={drafts.xero_user_id}
                onChange={(value) => setDraft('xero_user_id', value)}
                hint="Without a valid Xero payroll id this person is excluded from timesheets and payroll."
              />
              <TextField
                label={staff === null ? 'Password' : 'New password (leave blank to keep)'}
                type="password"
                automationId="StaffFormDialog-password"
                value={drafts.password}
                onChange={(value) => setDraft('password', value)}
              />
              <TextField
                label="Confirm password"
                type="password"
                automationId="StaffFormDialog-password-confirm"
                value={drafts.password_confirm}
                onChange={(value) => setDraft('password_confirm', value)}
              />
              <NumberField
                label="Base wage rate"
                automationId="StaffFormDialog-base-wage-rate"
                value={drafts.base_wage_rate}
                min={0}
                step={0.01}
                onChange={(value) => setDraft('base_wage_rate', value)}
              />
              <label className="flex flex-col gap-1 text-sm font-medium">
                <span className="text-slate-700">Costing rate</span>
                <input
                  type="text"
                  className={INPUT_CLASS}
                  value={staff === null ? '' : staff.wage_rate.toFixed(2)}
                  disabled
                  data-automation-id="StaffFormDialog-wage-rate"
                />
                <span className="text-xs font-normal text-slate-500">
                  Computed from the base rate with annual leave loading.
                </span>
              </label>
              <DateField
                label="Employment start date"
                automationId="StaffFormDialog-start-date"
                value={drafts.employment_start_date}
                onChange={(value) => setDraft('employment_start_date', value)}
              />
              <DateField
                label="Date left"
                automationId="StaffFormDialog-date-left"
                value={drafts.date_left}
                onChange={(value) => setDraft('date_left', value)}
                hint="Leave blank for current employees."
              />
              <label className="flex flex-col gap-1 text-sm font-medium">
                <span className="text-slate-700">Pay basis</span>
                <select
                  className={INPUT_CLASS}
                  value={drafts.pay_basis}
                  onChange={(event) => setDraft('pay_basis', requirePayBasis(event.target.value))}
                  data-automation-id="StaffFormDialog-pay-basis"
                >
                  <option value="">Not set</option>
                  <option value="hourly">Hourly</option>
                  <option value="salary">Salary</option>
                </select>
              </label>
              <div className="flex flex-col gap-1 text-sm font-medium">
                <span className="text-slate-700">Photo</span>
                <div className="flex items-center gap-3">
                  {iconUrl ? (
                    <img
                      src={iconUrl}
                      alt="Staff icon preview"
                      className="h-12 w-12 rounded-full border border-slate-200 object-cover"
                    />
                  ) : (
                    <span className="text-xs font-normal text-slate-500">No photo</span>
                  )}
                  <label className="inline-flex cursor-pointer items-center rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50 focus-within:ring-2 focus-within:ring-slate-400 focus-within:ring-offset-2">
                    {iconFile ? 'Change photo' : 'Choose photo'}
                    <input
                      type="file"
                      accept={ICON_ACCEPT}
                      className="sr-only"
                      aria-label="Upload staff photo"
                      data-automation-id="StaffFormDialog-icon"
                      onChange={(event) => {
                        const file = event.target.files?.[0]
                        event.target.value = ''
                        if (file) setIconFile(file)
                      }}
                    />
                  </label>
                </div>
                <span className="text-xs font-normal text-slate-500">Uploaded on save.</span>
              </div>
            </div>
          </FormSection>

          <FormSection title="Working hours">
            <div className="grid grid-cols-4 gap-x-4 gap-y-3 md:grid-cols-7">
              {HOUR_KEYS.map(([key, label]) => (
                <NumberField
                  key={key}
                  label={label}
                  automationId={`StaffFormDialog-${key.replace('_', '-')}`}
                  value={drafts.hours[key]}
                  min={0}
                  max={24}
                  step={0.25}
                  onChange={(value) => setDraft('hours', { ...drafts.hours, [key]: value })}
                />
              ))}
            </div>
          </FormSection>

          <FormSection title="Permissions">
            <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
              <FlagField
                label="Office staff"
                automationId="StaffFormDialog-office-staff"
                checked={drafts.flags.is_office_staff}
                onChange={(value) => setDraft('flags', { ...drafts.flags, is_office_staff: value })}
              />
              <FlagField
                label="Workshop staff"
                automationId="StaffFormDialog-workshop-staff"
                checked={drafts.flags.is_workshop_staff}
                onChange={(value) =>
                  setDraft('flags', { ...drafts.flags, is_workshop_staff: value })
                }
              />
              <FlagField
                label="Superuser"
                automationId="StaffFormDialog-superuser"
                checked={drafts.flags.is_superuser}
                onChange={(value) => setDraft('flags', { ...drafts.flags, is_superuser: value })}
              />
              <FlagField
                label="Staff manager"
                automationId="StaffFormDialog-staff-manager"
                checked={drafts.flags.is_staff_manager}
                onChange={(value) =>
                  setDraft('flags', { ...drafts.flags, is_staff_manager: value })
                }
              />
            </div>
          </FormSection>

          {validationError && (
            <p
              role="alert"
              className="text-sm text-red-700"
              data-automation-id="StaffFormDialog-validation"
            >
              {validationError}
            </p>
          )}
        </div>

        <DialogFooter>
          <Button
            variant="outline"
            disabled={saving}
            onClick={() => onOpenChange(false)}
            data-automation-id="StaffFormDialog-cancel"
          >
            Cancel
          </Button>
          <Button
            disabled={saving}
            onClick={() => void save()}
            data-automation-id="StaffFormDialog-submit"
          >
            {saving ? 'Saving…' : 'Save'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function FormSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
      {children}
    </section>
  )
}

function TextField({
  label,
  type = 'text',
  automationId,
  value,
  onChange,
  hint,
}: {
  label: string
  type?: 'text' | 'email' | 'password'
  automationId: string
  value: string
  onChange: (value: string) => void
  hint?: string
}) {
  return (
    <label className="flex flex-col gap-1 text-sm font-medium">
      <span className="text-slate-700">{label}</span>
      <input
        type={type}
        autoComplete={type === 'password' ? 'new-password' : undefined}
        className={INPUT_CLASS}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        data-automation-id={automationId}
      />
      {hint && <span className="text-xs font-normal text-slate-500">{hint}</span>}
    </label>
  )
}

function DateField({
  label,
  automationId,
  value,
  onChange,
  hint,
}: {
  label: string
  automationId: string
  value: string
  onChange: (value: string) => void
  hint?: string
}) {
  return (
    <label className="flex flex-col gap-1 text-sm font-medium">
      <span className="text-slate-700">{label}</span>
      <input
        type="date"
        className={INPUT_CLASS}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        data-automation-id={automationId}
      />
      {hint && <span className="text-xs font-normal text-slate-500">{hint}</span>}
    </label>
  )
}

function NumberField({
  label,
  automationId,
  value,
  min,
  max,
  step,
  onChange,
}: {
  label: string
  automationId: string
  value: string
  min: number
  max?: number
  step: number
  onChange: (value: string) => void
}) {
  return (
    <label className="flex flex-col gap-1 text-sm font-medium">
      <span className="text-slate-700">{label}</span>
      <input
        type="number"
        className={INPUT_CLASS}
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(event.target.value)}
        data-automation-id={automationId}
      />
    </label>
  )
}

function FlagField({
  label,
  automationId,
  checked,
  onChange,
}: {
  label: string
  automationId: string
  checked: boolean
  onChange: (value: boolean) => void
}) {
  return (
    <label className="flex items-center gap-2 text-sm font-medium">
      <input
        type="checkbox"
        className="h-4 w-4 rounded border-slate-300"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        data-automation-id={automationId}
      />
      <span className="text-slate-700">{label}</span>
    </label>
  )
}
