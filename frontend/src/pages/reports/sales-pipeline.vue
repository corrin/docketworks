<!--
  Sales Pipeline Report — question-driven layout.

  Top-to-bottom, every section is a real head-of-sales question. Spec lives in
  docs/plans/steady-sleeping-waffle.md and was negotiated word-by-word with the
  business owner; do not rearrange or rename sections without re-reading it.

  Reading order:
    Tier 1  — "Are we selling enough?"          (hero h/day verdict)
    Tier 2  — "Where is the leak?"              (funnel diagram)
    Tier 2.5 — "Recent or long pattern?"        (13-week sparkline)
    Tier 3  — "What did we win/lose/can chase?" (three drill-down lists)
-->
<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-7xl mx-auto py-8 px-2 md:px-8 h-full flex flex-col gap-8">
          <!-- Header / controls — minimal: end_date + analyse_workdays only. -->
          <div class="flex items-center justify-between">
            <h1
              data-automation-id="SalesPipelineReport-title"
              class="text-2xl font-bold text-gray-800 flex items-center gap-3"
            >
              <Activity class="w-6 h-6 text-indigo-500" />
              Sales Pipeline
            </h1>
            <div class="flex items-end gap-4">
              <div class="flex flex-col">
                <label for="end-date" class="text-xs font-medium text-gray-600 mb-1"> As of </label>
                <input
                  id="end-date"
                  v-model="filters.endDate"
                  type="date"
                  class="rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  @change="loadData"
                />
              </div>
              <div class="flex flex-col">
                <label for="analyse-workdays" class="text-xs font-medium text-gray-600 mb-1">
                  Analyse last (workdays)
                </label>
                <input
                  id="analyse-workdays"
                  v-model.number="filters.analyseWorkdays"
                  type="number"
                  min="1"
                  max="200"
                  class="w-28 rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  @change="loadData"
                />
              </div>
              <div class="flex flex-col">
                <label for="trend-workdays" class="text-xs font-medium text-gray-600 mb-1">
                  Trend back (workdays)
                </label>
                <input
                  id="trend-workdays"
                  v-model.number="filters.trendWorkdays"
                  type="number"
                  min="5"
                  max="500"
                  class="w-28 rounded border-gray-300 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                  @change="loadData"
                />
              </div>
              <Button
                variant="default"
                @click="loadData"
                :disabled="loading"
                class="text-sm px-4 py-2"
              >
                <RefreshCw class="w-4 h-4 mr-2" :class="{ 'animate-spin': loading }" />
                Refresh
              </Button>
            </div>
          </div>

          <!-- Loading state -->
          <div
            v-if="loading"
            data-automation-id="SalesPipelineReport-loading"
            class="flex items-center justify-center py-16"
          >
            <RefreshCw class="h-8 w-8 animate-spin text-indigo-500" />
            <span class="ml-2 text-lg text-gray-600">Loading sales pipeline...</span>
          </div>

          <!-- Error state -->
          <div v-else-if="error" class="bg-red-50 border border-red-200 rounded-lg p-4">
            <div class="flex items-center">
              <AlertCircle class="h-5 w-5 text-red-400 mr-2" />
              <span class="text-red-800">{{ error }}</span>
            </div>
          </div>

          <!-- Empty state -->
          <div
            v-else-if="!current || !baseline"
            class="bg-white rounded-lg shadow-sm border border-slate-200 p-8 text-center"
          >
            <Activity class="mx-auto h-12 w-12 text-gray-400" />
            <h3 class="mt-2 text-sm font-medium text-gray-900">No data loaded</h3>
            <p class="mt-1 text-sm text-gray-500">
              Adjust the controls above to view the pipeline.
            </p>
          </div>

          <!-- Report body -->
          <template v-else>
            <!-- ANSWERS: Are we selling enough? -->
            <section data-automation-id="SalesPipelineReport-tier1">
              <h2 class="text-lg font-semibold text-gray-700 mb-3">Are we selling enough?</h2>
              <component
                :is="VerdictHeadline"
                :actual-h-per-day="current.scoreboard.approved_hours_per_working_day"
                :target-h-per-day="current.period.daily_approved_hours_target"
                :normal-h-per-day="baseline.scoreboard.approved_hours_per_working_day"
                :pace-vs-target="current.scoreboard.pace_vs_target"
                :working-days="current.scoreboard.working_days"
              />
            </section>

            <!-- ANSWERS: Where is the leak? -->
            <section data-automation-id="SalesPipelineReport-tier2">
              <h2 class="text-lg font-semibold text-gray-700 mb-3">Where is the leak?</h2>
              <p class="text-sm text-gray-500 mb-4">
                Each stage shows what's happening now vs typical. Red = below normal, green = above
                normal. Both deserve attention — leaks need fixing, wins need capturing.
              </p>
              <component
                :is="FunnelDiagram"
                :current="current"
                :baseline="baseline"
                :scale="baselineScale"
              />
            </section>

            <!-- ANSWERS: Is this a recent thing or a long pattern? -->
            <section data-automation-id="SalesPipelineReport-tier25">
              <h2 class="text-base font-semibold text-gray-700 mb-3">
                Is this a recent thing or a long pattern?
              </h2>
              <component
                :is="TrendSparkline"
                :weeks="current.trend.weeks"
                :target-h-per-day="current.period.daily_approved_hours_target"
                :baseline-h-per-day="trailing12wkBaseline"
              />
            </section>

            <!-- ANSWERS: Three drill-down questions. -->
            <section
              data-automation-id="SalesPipelineReport-tier3"
              class="grid grid-cols-1 lg:grid-cols-3 gap-6"
            >
              <!-- ANSWERS: What did we win this period? -->
              <div id="tier-3-won">
                <h3 class="text-base font-semibold text-gray-700 mb-3">
                  What did we win this period?
                </h3>
                <component
                  :is="JobListTable"
                  :rows="[]"
                  empty-mode="placeholder"
                  :placeholder-summary="`${current.scoreboard.approved_jobs_count} jobs won · ${formatHPerDay(current.scoreboard.approved_hours_per_working_day)}`"
                  placeholder-note="Per-job won list ships in v1.5 (Task #13)."
                />
              </div>

              <!-- ANSWERS: What did we lose this period? -->
              <div id="tier-3-lost">
                <h3 class="text-base font-semibold text-gray-700 mb-3">
                  What did we lose this period?
                </h3>
                <component
                  :is="JobListTable"
                  :rows="[]"
                  empty-mode="placeholder"
                  :placeholder-summary="`${current.conversion_funnel.rejected.count} rejected · ${formatHPerDay(rejectedHPerDay)}`"
                  placeholder-note="Per-job lost list ships in v1.5 (Task #13)."
                />
              </div>

              <!-- ANSWERS: What can I chase to close the gap? -->
              <div id="tier-3-chase">
                <h3 class="text-base font-semibold text-gray-700 mb-3">
                  What can I chase to close the gap?
                </h3>
                <component
                  :is="JobListTable"
                  :rows="chaseRows"
                  empty-mode="rows"
                  :p80-days="current.velocity.quote_sent_to_resolved.p80_days"
                />
              </div>
            </section>
          </template>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import { Activity, AlertCircle, ArrowDown, RefreshCw } from 'lucide-vue-next'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { salesPipelineReportService } from '@/services/sales-pipeline-report.service'
import type {
  SalesPipelineResponse,
  SalesPipelineSnapshotJob,
  SalesPipelineTrendWeek,
} from '@/types/sales-pipeline.types'
import { toLocalDateString } from '@/utils/dateUtils'

// ---------- State ----------

const loading = ref(false)
const error = ref<string | null>(null)
const current = ref<SalesPipelineResponse | null>(null)
const baseline = ref<SalesPipelineResponse | null>(null)

const filters = ref({
  endDate: '',
  analyseWorkdays: 20,
  // Trend window in workdays (user's native unit). 65 ≈ 13 weeks of trading.
  // Converted to whole weeks for the backend (which accepts trend_weeks).
  trendWorkdays: 65,
})

// ---------- Formatting helpers ----------

function formatHPerDay(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(1)} h/day`
}

function formatNumber(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toFixed(digits)
}

function formatHours(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return `${value.toFixed(0)} h`
}

function sizeBucket(hours: number): 'small' | 'medium' | 'large' {
  if (hours < 8) return 'small'
  if (hours < 40) return 'medium'
  return 'large'
}

// Walk back N weekdays (Mon–Fri). The frontend has no NZ holiday calendar,
// so this is an approximation; the backend recomputes working_days inside
// the requested window using the proper NZ calendar, which is what we display.
function subtractWorkdays(date: Date, workdays: number): Date {
  const out = new Date(date)
  let remaining = workdays
  while (remaining > 0) {
    out.setDate(out.getDate() - 1)
    const dow = out.getDay()
    if (dow !== 0 && dow !== 6) remaining -= 1
  }
  return out
}

// ---------- Computed ----------

// Scaling factor: stretch baseline (~60-workday window) numbers down to a
// 20-workday equivalent so "current" and "normal" are apples-to-apples.
// Per-day rates are already scale-free (hours_per_working_day, etc.) and need
// no scaling. Counts and totals do.
const baselineScale = computed(() => {
  if (!current.value || !baseline.value) return 1
  const cur = current.value.scoreboard.working_days
  const base = baseline.value.scoreboard.working_days
  if (base <= 0) return 1
  return cur / base
})

// Per-day rejection rate, computed FE-side: rejected hours ÷ working days.
const rejectedHPerDay = computed(() => {
  if (!current.value) return null
  const wd = current.value.scoreboard.working_days
  if (wd <= 0) return null
  return current.value.conversion_funnel.rejected.hours / wd
})

// Trailing-12-week baseline value plotted as a horizontal line on the trend
// sparkline. Uses the current.trend.weeks payload (13 weeks back) and averages
// per-week h/day rates. Per-day rates so no scaling needed.
const trailing12wkBaseline = computed(() => {
  if (!current.value) return null
  const weeks = current.value.trend.weeks
  if (weeks.length === 0) return null
  const total = weeks.reduce((s, w) => s + w.approved_hours_per_working_day, 0)
  return total / weeks.length
})

// Awaiting-approval jobs sorted oldest-first — that's the call list.
interface ChaseRow {
  job: SalesPipelineSnapshotJob
  bucket: 'small' | 'medium' | 'large'
  isPathological: boolean
}
const chaseRows = computed<ChaseRow[]>(() => {
  if (!current.value) return []
  const jobs = [...current.value.pipeline_snapshot.awaiting_approval.jobs]
  jobs.sort((a, b) => b.days_in_stage - a.days_in_stage)
  const p80 = current.value.velocity.quote_sent_to_resolved.p80_days
  return jobs.map((job) => ({
    job,
    bucket: sizeBucket(job.hours),
    isPathological: p80 !== null && job.days_in_stage > p80,
  }))
})

// ---------- Inline subcomponents ----------

// ANSWERS: Are we selling enough? (the hero h/day number)
const VerdictHeadline = {
  props: {
    actualHPerDay: { type: Number as () => number | null, required: true },
    targetHPerDay: { type: Number, required: true },
    normalHPerDay: { type: Number as () => number | null, required: true },
    paceVsTarget: { type: Number as () => number | null, required: true },
    workingDays: { type: Number, required: true },
  },
  setup(props: {
    actualHPerDay: number | null
    targetHPerDay: number
    normalHPerDay: number | null
    paceVsTarget: number | null
    workingDays: number
  }) {
    const colour = () => {
      const p = props.paceVsTarget
      if (p === null) return { bar: 'bg-gray-300', text: 'text-gray-500', label: '—' }
      if (p < 0.8) return { bar: 'bg-red-500', text: 'text-red-700', label: 'RED' }
      if (p < 0.95) return { bar: 'bg-amber-500', text: 'text-amber-700', label: 'AMBER' }
      return { bar: 'bg-green-500', text: 'text-green-700', label: 'GREEN' }
    }
    return () => {
      const c = colour()
      const actualLabel = props.actualHPerDay === null ? '—' : props.actualHPerDay.toFixed(1)
      const pacePct =
        props.paceVsTarget === null ? null : Math.max(0, Math.min(150, props.paceVsTarget * 100))
      return h('div', { class: 'bg-white rounded-lg shadow-sm border border-slate-200 p-6' }, [
        // Hero number — the largest element on the page.
        h('div', { class: 'flex items-baseline gap-3' }, [
          h(
            'span',
            { class: ['text-7xl font-extrabold leading-none tracking-tight', c.text] },
            actualLabel,
          ),
          h('span', { class: ['text-2xl font-semibold', c.text] }, 'h/day'),
        ]),
        h(
          'p',
          { class: 'text-sm text-gray-500 mt-2' },
          `selling, last ${props.workingDays} working days`,
        ),
        h('p', { class: 'text-sm text-gray-700 mt-1' }, [
          `target ${props.targetHPerDay.toFixed(1)} h/day`,
          h('span', { class: 'text-gray-400 mx-2' }, '·'),
          `normal ${props.normalHPerDay === null ? '—' : props.normalHPerDay.toFixed(1)} h/day`,
        ]),
        // Supporting bar — smaller, lower; glance-confirmation only.
        h('div', { class: 'mt-4 max-w-xl' }, [
          h('div', { class: 'w-full h-3 rounded-full bg-gray-100 overflow-hidden' }, [
            pacePct === null
              ? null
              : h('div', {
                  class: ['h-full', c.bar],
                  style: { width: `${Math.min(100, pacePct)}%` },
                }),
          ]),
          h('div', { class: 'flex items-center justify-between mt-1 text-xs' }, [
            h(
              'span',
              { class: ['font-semibold', c.text] },
              `${pacePct === null ? '—' : pacePct.toFixed(0)}% of target`,
            ),
            h('span', { class: ['font-mono', c.text] }, c.label),
          ]),
        ]),
      ])
    }
  },
}

// One funnel node — a card carrying current vs normal numbers plus two
// English captions (one diagnostic, one actionable). Mid-range nodes show no
// caption (within ~5% of normal).
type Direction = 'below' | 'above' | 'mid'
interface NodeMetric {
  label: string
  current: string
  normal: string
}
const FunnelNode = {
  props: {
    title: { type: String, required: true },
    metrics: { type: Array as () => NodeMetric[], required: true },
    direction: { type: String as () => Direction, required: true },
    captionWhat: { type: String, default: '' },
    captionDo: { type: String, default: '' },
    captionLink: { type: String, default: '' },
  },
  setup(props: {
    title: string
    metrics: NodeMetric[]
    direction: Direction
    captionWhat: string
    captionDo: string
    captionLink: string
  }) {
    return () => {
      const colour =
        props.direction === 'below'
          ? { ring: 'ring-red-300', bg: 'bg-red-50', tag: 'bg-red-100 text-red-800' }
          : props.direction === 'above'
            ? { ring: 'ring-green-300', bg: 'bg-green-50', tag: 'bg-green-100 text-green-800' }
            : { ring: 'ring-slate-200', bg: 'bg-white', tag: 'bg-slate-100 text-slate-700' }
      const tagText =
        props.direction === 'below'
          ? 'BELOW NORMAL'
          : props.direction === 'above'
            ? 'ABOVE NORMAL'
            : 'NORMAL'
      const showCaptions = props.direction !== 'mid' && (props.captionWhat || props.captionDo)

      return h(
        'div',
        {
          class: [
            'rounded-lg shadow-sm border border-slate-200 ring-2 p-4',
            colour.ring,
            colour.bg,
          ],
        },
        [
          h('div', { class: 'flex items-center justify-between mb-3' }, [
            h(
              'h3',
              { class: 'text-sm font-bold uppercase tracking-wider text-gray-800' },
              props.title,
            ),
            h(
              'span',
              {
                class: [
                  'text-[10px] font-semibold px-2 py-0.5 rounded uppercase tracking-wider',
                  colour.tag,
                ],
              },
              tagText,
            ),
          ]),
          h(
            'div',
            {
              class: 'grid gap-2',
              style: { gridTemplateColumns: 'auto 1fr 1fr' },
            },
            [
              h('span', {}),
              h('span', { class: 'text-[10px] uppercase font-semibold text-gray-500' }, 'now'),
              h('span', { class: 'text-[10px] uppercase font-semibold text-gray-500' }, 'normal'),
              ...props.metrics.flatMap((m) => [
                h('span', { class: 'text-xs text-gray-600' }, m.label),
                h(
                  'span',
                  { class: 'text-base font-semibold text-gray-900 tabular-nums' },
                  m.current,
                ),
                h('span', { class: 'text-base text-gray-500 tabular-nums' }, m.normal),
              ]),
            ],
          ),
          showCaptions
            ? h('div', { class: 'mt-3 space-y-1 text-xs' }, [
                props.captionWhat
                  ? h(
                      'p',
                      {
                        class: [
                          'italic',
                          props.direction === 'below' ? 'text-red-800' : 'text-green-800',
                        ],
                      },
                      props.captionWhat,
                    )
                  : null,
                props.captionDo
                  ? h('p', { class: 'text-gray-700' }, [
                      props.captionDo,
                      props.captionLink
                        ? h(
                            'a',
                            {
                              href: props.captionLink,
                              class: 'ml-1 text-indigo-600 hover:text-indigo-800 underline',
                            },
                            'see list',
                          )
                        : null,
                    ])
                  : null,
              ])
            : null,
        ],
      )
    }
  },
}

// Diagnostic-deviation classifier: compare current to normal, with a ~5%
// dead-band around parity. Below = red, above = green, mid = no caption.
function classify(curr: number | null, normal: number | null): Direction {
  if (curr === null || normal === null) return 'mid'
  if (normal === 0) return curr > 0 ? 'above' : 'mid'
  const ratio = curr / normal
  if (ratio < 0.95) return 'below'
  if (ratio > 1.05) return 'above'
  return 'mid'
}

// ANSWERS: Where is the leak? — the funnel diagram itself.
const FunnelDiagram = {
  props: {
    current: { type: Object as () => SalesPipelineResponse, required: true },
    baseline: { type: Object as () => SalesPipelineResponse, required: true },
    scale: { type: Number, required: true },
  },
  setup(props: { current: SalesPipelineResponse; baseline: SalesPipelineResponse; scale: number }) {
    const arrow = () =>
      h(
        'div',
        { class: 'flex justify-center my-1 text-gray-400' },
        h(ArrowDown, { class: 'w-5 h-5' }),
      )

    return () => {
      const cur = props.current
      const base = props.baseline

      // LEADS — derived from sum of conversion_funnel buckets.
      // Counts scale (current is 20-workday window vs baseline ~60), so we
      // normalise the baseline count down to current.working_days.
      const sumFunnelCount = (r: SalesPipelineResponse) =>
        r.conversion_funnel.accepted.count +
        r.conversion_funnel.direct.count +
        r.conversion_funnel.rejected.count +
        r.conversion_funnel.waiting.count +
        r.conversion_funnel.still_draft.count
      const sumFunnelHours = (r: SalesPipelineResponse) =>
        r.conversion_funnel.accepted.hours +
        r.conversion_funnel.direct.hours +
        r.conversion_funnel.rejected.hours +
        r.conversion_funnel.waiting.hours +
        r.conversion_funnel.still_draft.hours

      const leadsNowCount = sumFunnelCount(cur)
      const leadsNormalCount = sumFunnelCount(base) * props.scale
      const leadsNowHpd =
        cur.scoreboard.working_days > 0 ? sumFunnelHours(cur) / cur.scoreboard.working_days : null
      const leadsNormalHpd =
        base.scoreboard.working_days > 0
          ? sumFunnelHours(base) / base.scoreboard.working_days
          : null
      const leadsDir = classify(leadsNowHpd, leadsNormalHpd)

      // STUCK IN DRAFT — pipeline snapshot is point-in-time; counts don't
      // need scaling. Compare current snapshot to baseline snapshot.
      const draftDir = classify(
        cur.pipeline_snapshot.draft.count,
        base.pipeline_snapshot.draft.count,
      )

      // AWAITING — same shape as DRAFT.
      const awaitingDir = classify(
        cur.pipeline_snapshot.awaiting_approval.count,
        base.pipeline_snapshot.awaiting_approval.count,
      )
      const awaitingHours = cur.pipeline_snapshot.awaiting_approval.hours_total
      const awaitingBacklogDays =
        cur.period.daily_approved_hours_target > 0
          ? awaitingHours / cur.period.daily_approved_hours_target
          : null

      // APPROVED — by funnel path. Per-day rate so no scaling needed.
      const estNowHpd = cur.scoreboard.by_funnel_path.estimating.hours_per_working_day
      const estNormalHpd = base.scoreboard.by_funnel_path.estimating.hours_per_working_day
      const estDir = classify(estNowHpd, estNormalHpd)

      const instNowHpd = cur.scoreboard.by_funnel_path.instant.hours_per_working_day
      const instNormalHpd = base.scoreboard.by_funnel_path.instant.hours_per_working_day
      const instDir = classify(instNowHpd, instNormalHpd)

      // REJECTED — h/day computed FE-side from funnel hours ÷ working days.
      const rejNowHpd =
        cur.scoreboard.working_days > 0
          ? cur.conversion_funnel.rejected.hours / cur.scoreboard.working_days
          : null
      const rejNormalHpd =
        base.scoreboard.working_days > 0
          ? base.conversion_funnel.rejected.hours / base.scoreboard.working_days
          : null
      // Rejected is "more = worse"; flip the direction so red still means bad.
      const rejDirRaw = classify(rejNowHpd, rejNormalHpd)
      const rejDir: Direction =
        rejDirRaw === 'above' ? 'below' : rejDirRaw === 'below' ? 'above' : 'mid'

      const cap = (
        title: string,
        dir: Direction,
        below: { what: string; do: string; link?: string },
        above: { what: string; do: string },
      ) => {
        if (dir === 'below') return { ...below }
        if (dir === 'above') return { ...above, link: '' }
        return { what: '', do: '', link: '' }
      }

      const leadsCap = cap(
        'leads',
        leadsDir,
        {
          what: 'Leads drying up — fewer prospects entering the funnel.',
          do: 'More outreach / marketing needed; check repeat-customer rate.',
        },
        {
          what: 'More leads than usual.',
          do: 'What changed? — repeat customers, marketing campaign, referrals? Capture so it can be repeated.',
        },
      )
      const draftCap = cap(
        'draft',
        draftDir,
        {
          what: 'Internal bottleneck — quotes piling up before they go out.',
          do: 'Look at estimator capacity.',
        },
        {
          what: 'Quotes going out faster than usual.',
          do: 'Good — keep the process light.',
        },
      )
      const awaitingCap = cap(
        'awaiting',
        awaitingDir,
        {
          what: 'Customers sitting on quotes longer than usual.',
          do: 'Chase the oldest first.',
          link: '#tier-3-chase',
        },
        {
          what: 'Customers responding faster than usual.',
          do: 'What changed? — pricing, quote clarity, customer mix? Capture it.',
        },
      )
      const estCap = cap(
        'estimating',
        estDir,
        {
          what: 'Acceptance rate on quoted work down.',
          do: 'Review pricing, quote clarity, or competitor activity.',
          link: '#tier-3-lost',
        },
        {
          what: 'Acceptance rate on quoted work up.',
          do: 'Is it pricing, sales effort, or product mix? Capture it.',
        },
      )
      const instCap = cap(
        'instant',
        instDir,
        {
          what: 'Walk-in / repeat work down.',
          do: 'Regulars losing interest? Customer-relationship review.',
        },
        {
          what: 'Walk-in / repeat work up.',
          do: "What's bringing the regulars back?",
        },
      )
      const rejCap = cap(
        'rejected',
        rejDir,
        {
          what: 'Losing more deals than usual.',
          do: 'Review what we lost and why.',
          link: '#tier-3-lost',
        },
        {
          what: 'Fewer rejections than usual.',
          do: 'Quote quality up, or are customers being less choosy?',
        },
      )

      const formatCount = (v: number) => (Number.isFinite(v) ? Math.round(v).toString() : '—')

      return h('div', { class: 'space-y-2' }, [
        h(FunnelNode, {
          title: 'Leads (jobs created)',
          metrics: [
            {
              label: 'h/day created',
              current: formatHPerDay(leadsNowHpd),
              normal: formatHPerDay(leadsNormalHpd),
            },
            {
              label: 'jobs in window',
              current: formatCount(leadsNowCount),
              normal: formatCount(leadsNormalCount),
            },
          ],
          direction: leadsDir,
          captionWhat: leadsCap.what,
          captionDo: leadsCap.do,
          captionLink: leadsCap.link ?? '',
        }),
        arrow(),
        h(FunnelNode, {
          title: 'Stuck in draft',
          metrics: [
            {
              label: 'jobs sitting',
              current: formatCount(cur.pipeline_snapshot.draft.count),
              normal: formatCount(base.pipeline_snapshot.draft.count),
            },
            {
              label: 'hours sitting',
              current: formatHours(cur.pipeline_snapshot.draft.hours_total),
              normal: formatHours(base.pipeline_snapshot.draft.hours_total),
            },
            {
              label: 'avg days in stage',
              current: formatNumber(cur.pipeline_snapshot.draft.avg_days_in_stage, 1),
              normal: formatNumber(base.pipeline_snapshot.draft.avg_days_in_stage, 1),
            },
          ],
          direction: draftDir,
          captionWhat: draftCap.what,
          captionDo: draftCap.do,
          captionLink: draftCap.link ?? '',
        }),
        arrow(),
        h(FunnelNode, {
          title: 'Awaiting customer',
          metrics: [
            {
              label: 'jobs sitting',
              current: formatCount(cur.pipeline_snapshot.awaiting_approval.count),
              normal: formatCount(base.pipeline_snapshot.awaiting_approval.count),
            },
            {
              label: 'hours sitting',
              current: formatHours(cur.pipeline_snapshot.awaiting_approval.hours_total),
              normal: formatHours(base.pipeline_snapshot.awaiting_approval.hours_total),
            },
            {
              label: 'avg days waiting',
              current: formatNumber(cur.pipeline_snapshot.awaiting_approval.avg_days_in_stage, 1),
              normal: formatNumber(base.pipeline_snapshot.awaiting_approval.avg_days_in_stage, 1),
            },
          ],
          direction: awaitingDir,
          captionWhat: awaitingCap.what,
          captionDo: awaitingCap.do
            ? `${awaitingCap.do} (≈${
                awaitingBacklogDays === null ? '—' : awaitingBacklogDays.toFixed(0)
              } days of work backlog at ${cur.period.daily_approved_hours_target.toFixed(0)} h/day)`
            : '',
          captionLink: awaitingCap.link ?? '',
        }),
        arrow(),
        h('div', { class: 'grid grid-cols-1 md:grid-cols-2 gap-3' }, [
          h(FunnelNode, {
            title: 'Approved — via quote (estimating)',
            metrics: [
              {
                label: 'h/day approved',
                current: formatHPerDay(estNowHpd),
                normal: formatHPerDay(estNormalHpd),
              },
              {
                label: 'jobs',
                current: formatCount(cur.scoreboard.by_funnel_path.estimating.count),
                normal: formatCount(base.scoreboard.by_funnel_path.estimating.count * props.scale),
              },
            ],
            direction: estDir,
            captionWhat: estCap.what,
            captionDo: estCap.do,
            captionLink: estCap.link ?? '',
          }),
          h(FunnelNode, {
            title: 'Approved — instant (<1h)',
            metrics: [
              {
                label: 'h/day approved',
                current: formatHPerDay(instNowHpd),
                normal: formatHPerDay(instNormalHpd),
              },
              {
                label: 'jobs',
                current: formatCount(cur.scoreboard.by_funnel_path.instant.count),
                normal: formatCount(base.scoreboard.by_funnel_path.instant.count * props.scale),
              },
            ],
            direction: instDir,
            captionWhat: instCap.what,
            captionDo: instCap.do,
            captionLink: instCap.link ?? '',
          }),
        ]),
        arrow(),
        h(FunnelNode, {
          title: 'Rejected',
          metrics: [
            {
              label: 'h/day lost',
              current: formatHPerDay(rejNowHpd),
              normal: formatHPerDay(rejNormalHpd),
            },
            {
              label: 'jobs rejected',
              current: formatCount(cur.conversion_funnel.rejected.count),
              normal: formatCount(base.conversion_funnel.rejected.count * props.scale),
            },
          ],
          direction: rejDir,
          captionWhat: rejCap.what,
          captionDo: rejCap.do,
          captionLink: rejCap.link ?? '',
        }),
      ])
    }
  },
}

// ANSWERS: Is this a recent thing or a long pattern? (sparkline)
const TrendSparkline = {
  props: {
    weeks: {
      type: Array as () => SalesPipelineTrendWeek[],
      required: true,
    },
    targetHPerDay: { type: Number, required: true },
    baselineHPerDay: { type: Number as () => number | null, required: true },
  },
  setup(props: {
    weeks: SalesPipelineTrendWeek[]
    targetHPerDay: number
    baselineHPerDay: number | null
  }) {
    const W = 800
    const H = 160
    const PAD_L = 36
    const PAD_R = 12
    const PAD_T = 12
    const PAD_B = 24

    return () => {
      const weeks = props.weeks
      if (weeks.length === 0) {
        return h(
          'div',
          {
            class:
              'bg-white rounded-lg shadow-sm border border-slate-200 p-4 text-sm text-gray-500',
          },
          'No trend data yet.',
        )
      }
      const values = weeks.map((w) => w.approved_hours_per_working_day)
      const yMaxRaw = Math.max(props.targetHPerDay + 5, ...values)
      const yMax = Math.ceil(yMaxRaw / 10) * 10
      const xFor = (i: number) => PAD_L + (i / Math.max(weeks.length - 1, 1)) * (W - PAD_L - PAD_R)
      const yFor = (v: number) => PAD_T + (1 - v / yMax) * (H - PAD_T - PAD_B)

      const points = weeks
        .map((w, i) => `${xFor(i)},${yFor(w.approved_hours_per_working_day)}`)
        .join(' ')

      // Auto-direction caption: count consecutive deltas at the tail.
      let runDown = 0
      let runUp = 0
      for (let i = weeks.length - 1; i > 0; i -= 1) {
        const d =
          weeks[i].approved_hours_per_working_day - weeks[i - 1].approved_hours_per_working_day
        if (d < 0 && runUp === 0) runDown += 1
        else if (d > 0 && runDown === 0) runUp += 1
        else break
      }
      const caption =
        runDown >= 2
          ? `Down ${runDown} weeks running`
          : runUp >= 2
            ? `Up ${runUp} weeks running`
            : 'Steady'

      const highlightStart = Math.max(0, weeks.length - 4)

      return h('div', { class: 'bg-white rounded-lg shadow-sm border border-slate-200 p-4' }, [
        h(
          'svg',
          {
            viewBox: `0 0 ${W} ${H}`,
            class: 'w-full h-40',
            role: 'img',
            'aria-label': '13-week sparkline of approved hours per working day',
          },
          [
            // Y axis ticks
            ...[0, yMax / 2, yMax].map((tick) =>
              h('g', { key: `tick-${tick}` }, [
                h('line', {
                  x1: PAD_L,
                  x2: W - PAD_R,
                  y1: yFor(tick),
                  y2: yFor(tick),
                  stroke: '#f3f4f6',
                }),
                h(
                  'text',
                  {
                    x: PAD_L - 6,
                    y: yFor(tick) + 4,
                    'font-size': 10,
                    'text-anchor': 'end',
                    fill: '#9ca3af',
                  },
                  tick.toFixed(0),
                ),
              ]),
            ),
            // Highlighted recent-4 weeks band
            h('rect', {
              x: xFor(highlightStart),
              y: PAD_T,
              width: xFor(weeks.length - 1) - xFor(highlightStart),
              height: H - PAD_T - PAD_B,
              fill: '#eef2ff',
            }),
            // Target line
            h('line', {
              x1: PAD_L,
              x2: W - PAD_R,
              y1: yFor(props.targetHPerDay),
              y2: yFor(props.targetHPerDay),
              stroke: '#10b981',
              'stroke-dasharray': '4 4',
              'stroke-width': 1.5,
            }),
            h(
              'text',
              {
                x: W - PAD_R,
                y: yFor(props.targetHPerDay) - 4,
                'font-size': 10,
                'text-anchor': 'end',
                fill: '#10b981',
              },
              `target ${props.targetHPerDay.toFixed(0)}`,
            ),
            // Baseline line
            props.baselineHPerDay === null
              ? null
              : h('line', {
                  x1: PAD_L,
                  x2: W - PAD_R,
                  y1: yFor(props.baselineHPerDay),
                  y2: yFor(props.baselineHPerDay),
                  stroke: '#6366f1',
                  'stroke-dasharray': '2 4',
                  'stroke-width': 1,
                }),
            props.baselineHPerDay === null
              ? null
              : h(
                  'text',
                  {
                    x: W - PAD_R,
                    y: yFor(props.baselineHPerDay) - 4,
                    'font-size': 10,
                    'text-anchor': 'end',
                    fill: '#6366f1',
                  },
                  `baseline ${props.baselineHPerDay.toFixed(1)}`,
                ),
            // Series line
            h('polyline', {
              points,
              fill: 'none',
              stroke: '#374151',
              'stroke-width': 2,
            }),
            // Points
            ...weeks.map((w, i) =>
              h('circle', {
                key: `pt-${w.week_start}`,
                cx: xFor(i),
                cy: yFor(w.approved_hours_per_working_day),
                r: i >= highlightStart ? 3.5 : 2.5,
                fill: i >= highlightStart ? '#1f2937' : '#9ca3af',
              }),
            ),
          ],
        ),
        h('p', { class: 'text-sm font-medium text-gray-700 mt-2' }, caption),
      ])
    }
  },
}

// ANSWERS: the three Tier-3 lists. Renders either an empty-state placeholder
// (won/lost — backend doesn't expose per-job lists yet) or full rows
// (chase — uses awaiting_approval.jobs).
const JobListTable = {
  props: {
    rows: { type: Array as () => ChaseRow[], required: true },
    emptyMode: {
      type: String as () => 'placeholder' | 'rows',
      required: true,
    },
    placeholderSummary: { type: String, default: '' },
    placeholderNote: { type: String, default: '' },
    p80Days: { type: Number as () => number | null, default: null },
  },
  setup(props: {
    rows: ChaseRow[]
    emptyMode: 'placeholder' | 'rows'
    placeholderSummary: string
    placeholderNote: string
    p80Days: number | null
  }) {
    return () => {
      if (props.emptyMode === 'placeholder') {
        return h(
          'div',
          {
            class: 'bg-white rounded-lg shadow-sm border border-slate-200 p-4',
          },
          [
            h('p', { class: 'text-base font-semibold text-gray-900' }, props.placeholderSummary),
            h('p', { class: 'text-xs text-gray-500 mt-2 italic' }, props.placeholderNote),
          ],
        )
      }
      if (props.rows.length === 0) {
        return h(
          'div',
          {
            class: 'bg-white rounded-lg shadow-sm border border-slate-200 p-4',
          },
          h('p', { class: 'text-sm text-gray-500 italic' }, 'Nothing awaiting customer right now.'),
        )
      }
      const p80Label =
        props.p80Days === null ? 'days old' : `days old (typ p80 ${props.p80Days.toFixed(0)}d)`
      return h(
        'div',
        {
          class: 'bg-white rounded-lg shadow-sm border border-slate-200 overflow-hidden',
        },
        [
          h(
            'div',
            { class: 'overflow-x-auto max-h-96' },
            h('table', { class: 'min-w-full text-sm divide-y divide-gray-200' }, [
              h(
                'thead',
                { class: 'bg-gray-50 sticky top-0' },
                h('tr', {}, [
                  h(
                    'th',
                    {
                      class:
                        'px-3 py-2 text-left text-[10px] uppercase font-semibold text-gray-500',
                    },
                    '#',
                  ),
                  h(
                    'th',
                    {
                      class:
                        'px-3 py-2 text-left text-[10px] uppercase font-semibold text-gray-500',
                    },
                    'name',
                  ),
                  h(
                    'th',
                    {
                      class:
                        'px-3 py-2 text-left text-[10px] uppercase font-semibold text-gray-500',
                    },
                    'size',
                  ),
                  h(
                    'th',
                    {
                      class:
                        'px-3 py-2 text-right text-[10px] uppercase font-semibold text-gray-500',
                    },
                    p80Label,
                  ),
                ]),
              ),
              h(
                'tbody',
                { class: 'divide-y divide-gray-100' },
                props.rows.map((row) =>
                  h(
                    'tr',
                    {
                      key: row.job.id,
                      class: row.isPathological ? 'bg-red-50' : '',
                    },
                    [
                      h(
                        'td',
                        { class: 'px-3 py-2 font-medium text-gray-900 tabular-nums' },
                        `#${row.job.job_number}`,
                      ),
                      h(
                        'td',
                        { class: 'px-3 py-2 text-gray-700 truncate max-w-[180px]' },
                        row.job.name,
                      ),
                      h('td', { class: 'px-3 py-2 text-gray-500' }, row.bucket),
                      h(
                        'td',
                        {
                          class: [
                            'px-3 py-2 text-right tabular-nums',
                            row.isPathological ? 'text-red-700 font-semibold' : 'text-gray-700',
                          ],
                        },
                        String(row.job.days_in_stage),
                      ),
                    ],
                  ),
                ),
              ),
            ]),
          ),
        ],
      )
    }
  },
}

// ---------- Data loading ----------

async function loadData() {
  if (!filters.value.endDate) {
    error.value = 'End date is required.'
    return
  }
  const N = filters.value.analyseWorkdays
  if (!Number.isFinite(N) || N <= 0) {
    error.value = 'Analyse workdays must be a positive whole number.'
    return
  }
  const T = filters.value.trendWorkdays
  if (!Number.isFinite(T) || T <= 0) {
    error.value = 'Trend workdays must be a positive whole number.'
    return
  }

  loading.value = true
  error.value = null
  try {
    const endDate = new Date(filters.value.endDate)
    const currentStart = subtractWorkdays(endDate, N)

    // Convert the user's "trend back N workdays" to whole weeks for the
    // backend (which accepts trend_weeks). 5 workdays ≈ 1 week; round up so
    // a request for 65 workdays maps to 13 weeks (the natural mapping).
    const trendWeeks = Math.max(1, Math.ceil(T / 5))

    // Baseline window: 12 weeks before current's start, ending the day before.
    const baselineEnd = new Date(currentStart)
    baselineEnd.setDate(baselineEnd.getDate() - 1)
    const baselineStart = new Date(baselineEnd)
    baselineStart.setDate(baselineStart.getDate() - 12 * 7)

    const both = await salesPipelineReportService.getCurrentAndBaseline({
      current: {
        start_date: toLocalDateString(currentStart),
        end_date: filters.value.endDate,
        rolling_window_weeks: 4,
        trend_weeks: trendWeeks,
      },
      baseline: {
        start_date: toLocalDateString(baselineStart),
        end_date: toLocalDateString(baselineEnd),
        rolling_window_weeks: 4,
        trend_weeks: 1,
      },
    })
    current.value = both.current
    baseline.value = both.baseline
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load sales pipeline report.'
    current.value = null
    baseline.value = null
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  filters.value.endDate = toLocalDateString(new Date())
  filters.value.analyseWorkdays = 20
  filters.value.trendWorkdays = 65
  loadData()
})
</script>
