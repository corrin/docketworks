import { useQuery } from '@tanstack/react-query'
import { Minus, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'

import { timesheetsJobsRetrieveOptions } from '@/api'
import type { FillOut, FillRowIn, TimesheetJobOut } from '@/api'
import { Button } from '@/components/ui/button'
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerTitle,
} from '@/components/ui/drawer'
import { INPUT_CLASS } from '@/components/ui/field'
import { TOUCH_TARGET_CLASS } from '@/components/ui/touch'
import { JobPicker } from '@/features/shared/JobPicker'
import { formatDateLong, formatHoursDisplay } from '@/lib/format'

import { fillAfterRows, fillWords, jobsInOrder, type FillSheetRow } from './myTime'
import { timesheetJobSearchOptions } from './timesheetJobSearch'

const QUARTER_HOUR = 0.25
/** One-tap lengths; anything else is a tap or two on the stepper. */
const HOUR_CHIPS = [1, 2, 3, 4]

interface FillDaySheetProps {
  open: boolean
  /** The day being filled, YYYY-MM-DD. */
  date: string
  /** The server's figures for the day as saved. */
  fill: FillOut
  sending: boolean
  onSend: (rows: FillRowIn[]) => Promise<boolean>
  onClose: () => void
}

/**
 * The fill sheet: the worker says what he did as jobs and hours, and never
 * a start time, an end time or a total. The jobs he is likeliest to mean are
 * buttons; "the rest" takes whatever is left of the time he was here.
 */
export function FillDaySheet({ open, date, fill, sending, onSend, onClose }: FillDaySheetProps) {
  // Asked for when the sheet opens, not when the page does: a closed sheet
  // needs no job list, and the list is a few hundred jobs.
  const jobsQuery = useQuery({ ...timesheetsJobsRetrieveOptions(), enabled: open })
  const jobs = jobsQuery.data?.jobs ?? []
  const pinned = jobsInOrder(jobsQuery.data?.pinned_job_ids ?? [], jobs)
  const recent = jobsInOrder(jobsQuery.data?.recent_job_ids ?? [], jobs)
  const [rows, setRows] = useState<FillSheetRow[]>([])
  const [nextKey, setNextKey] = useState(0)

  const running = fillAfterRows(fill, rows)
  const allSized = rows.every((row) => row.hours !== null && row.hours > 0)

  const addRow = (job: TimesheetJobOut) => {
    setRows([...rows, { key: nextKey, job, hours: null, timeAndAHalf: false, description: '' }])
    setNextKey(nextKey + 1)
  }
  const change = (key: number, patch: Partial<FillSheetRow>) =>
    setRows(rows.map((row) => (row.key === key ? { ...row, ...patch } : row)))

  const send = async () => {
    const sent = await onSend(
      rows.flatMap((row) =>
        row.hours === null
          ? []
          : [
              {
                job_id: row.job.id,
                hours: row.hours,
                description: row.description.trim() === '' ? null : row.description.trim(),
                time_and_a_half: row.timeAndAHalf,
              },
            ],
      ),
    )
    if (sent) {
      setRows([])
      onClose()
    }
  }

  return (
    <Drawer
      open={open}
      onOpenChange={(nowOpen) => {
        if (!nowOpen && !sending) onClose()
      }}
    >
      <DrawerContent className="max-h-[92vh]" data-automation-id="FillDaySheet">
        <div className="mx-auto w-full max-w-md overflow-y-auto">
          <DrawerHeader>
            <DrawerTitle>Fill the day</DrawerTitle>
            <DrawerDescription>{formatDateLong(date)}</DrawerDescription>
          </DrawerHeader>

          <div className="space-y-4 px-4 pb-2">
            <p
              className="text-base font-semibold text-gray-900"
              data-automation-id="FillDaySheet-sum"
            >
              {fillWords(running)}
            </p>

            {rows.map((row) => {
              // What "the rest" gives this row: everything left, counting the
              // hours it already holds.
              const rest = running.to_go_hours + (row.hours ?? 0)
              return (
                <div
                  key={row.key}
                  className="space-y-2 rounded border border-slate-200 p-3"
                  data-automation-id={`FillDaySheet-row-${row.key}`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <span className="min-w-0 truncate text-sm font-medium text-gray-900">
                      #{row.job.job_number} {row.job.name}
                    </span>
                    <Button
                      variant="outline"
                      size="icon"
                      className={TOUCH_TARGET_CLASS}
                      aria-label="Remove row"
                      data-automation-id={`FillDaySheet-row-${row.key}-remove`}
                      onClick={() => setRows(rows.filter((other) => other.key !== row.key))}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {HOUR_CHIPS.map((hours) => (
                      <Button
                        key={hours}
                        variant={row.hours === hours ? 'default' : 'outline'}
                        className={TOUCH_TARGET_CLASS}
                        data-automation-id={`FillDaySheet-row-${row.key}-hours-${hours}`}
                        onClick={() => change(row.key, { hours })}
                      >
                        {hours}h
                      </Button>
                    ))}
                    {rest > 0 && (
                      <Button
                        variant={row.hours === rest ? 'default' : 'outline'}
                        className={TOUCH_TARGET_CLASS}
                        data-automation-id={`FillDaySheet-row-${row.key}-rest`}
                        onClick={() => change(row.key, { hours: rest })}
                      >
                        The rest ({formatHoursDisplay(rest)})
                      </Button>
                    )}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="icon"
                      className={TOUCH_TARGET_CLASS}
                      aria-label="Quarter of an hour less"
                      disabled={row.hours === null || row.hours <= QUARTER_HOUR}
                      data-automation-id={`FillDaySheet-row-${row.key}-less`}
                      onClick={() => change(row.key, { hours: (row.hours ?? 0) - QUARTER_HOUR })}
                    >
                      <Minus />
                    </Button>
                    {/* Typed or tapped, his choice: the chips and the stepper
                        set this same number. */}
                    <input
                      type="number"
                      inputMode="decimal"
                      min={QUARTER_HOUR}
                      step={QUARTER_HOUR}
                      value={row.hours ?? ''}
                      placeholder="Hours"
                      aria-label="Hours"
                      className={`${INPUT_CLASS} ${TOUCH_TARGET_CLASS} w-24 text-center text-base font-semibold`}
                      data-automation-id={`FillDaySheet-row-${row.key}-hours`}
                      onChange={(event) =>
                        change(row.key, {
                          hours: event.target.value === '' ? null : Number(event.target.value),
                        })
                      }
                    />
                    <Button
                      variant="outline"
                      size="icon"
                      className={TOUCH_TARGET_CLASS}
                      aria-label="Quarter of an hour more"
                      data-automation-id={`FillDaySheet-row-${row.key}-more`}
                      onClick={() => change(row.key, { hours: (row.hours ?? 0) + QUARTER_HOUR })}
                    >
                      <Plus />
                    </Button>
                    <label className="ml-auto flex items-center gap-2 text-sm text-gray-700">
                      <input
                        type="checkbox"
                        className="h-5 w-5"
                        checked={row.timeAndAHalf}
                        data-automation-id={`FillDaySheet-row-${row.key}-time-and-a-half`}
                        onChange={(event) =>
                          change(row.key, { timeAndAHalf: event.target.checked })
                        }
                      />
                      Time and a half
                    </label>
                  </div>
                  <input
                    type="text"
                    value={row.description}
                    placeholder="What was it? (optional)"
                    aria-label="Description"
                    className={INPUT_CLASS}
                    data-automation-id={`FillDaySheet-row-${row.key}-description`}
                    onChange={(event) => change(row.key, { description: event.target.value })}
                  />
                </div>
              )
            })}

            <div className="space-y-2" data-automation-id="FillDaySheet-jobs">
              <p className="text-sm font-medium text-gray-700">Add a job</p>
              <div className="flex flex-wrap gap-2">
                {[...pinned, ...recent].map((job) => (
                  <Button
                    key={job.id}
                    variant="outline"
                    className={`${TOUCH_TARGET_CLASS} max-w-full`}
                    data-automation-id={`FillDaySheet-job-${job.job_number}`}
                    onClick={() => addRow(job)}
                  >
                    <span className="truncate">
                      #{job.job_number} {job.name}
                    </span>
                  </Button>
                ))}
              </div>
              <div className="rounded border border-slate-200">
                <JobPicker
                  triggerClassName={TOUCH_TARGET_CLASS}
                  automationIdPrefix="FillDaySheet-job-picker"
                  ariaLabel="Another job"
                  jobs={jobs}
                  selected={null}
                  disabled={sending}
                  loading={jobsQuery.isPending}
                  placeholder="Another job"
                  triggerLabel={() => ''}
                  typedSearchLimit={null}
                  commitOnTab={false}
                  searchOptions={timesheetJobSearchOptions}
                  onSelect={addRow}
                />
              </div>
            </div>
          </div>

          <DrawerFooter>
            <div className="flex items-center gap-2">
              <Button
                className={`flex-1 ${TOUCH_TARGET_CLASS}`}
                disabled={sending || !allSized}
                data-automation-id="FillDaySheet-send"
                onClick={() => void send()}
              >
                Send to office
              </Button>
              <Button
                variant="outline"
                className={TOUCH_TARGET_CLASS}
                disabled={sending}
                data-automation-id="FillDaySheet-cancel"
                onClick={onClose}
              >
                Not yet
              </Button>
            </div>
          </DrawerFooter>
        </div>
      </DrawerContent>
    </Drawer>
  )
}
