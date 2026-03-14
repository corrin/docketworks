<template>
  <div class="job-quote-tab h-full flex flex-col">
    <div class="flex-shrink-0 mb-6">
      <div class="flex items-center justify-between">
        <div>
          <h2 class="text-2xl font-bold text-gray-900 mb-2">
            Quote Management{{
              currentQuote?.has_quote ? ` - Revision ${currentQuote.quote?.rev}` : ''
            }}
          </h2>
        </div>
      </div>
    </div>

    <!-- CONTENT: STICKY GRID ASIDE + MAIN -->
    <div class="flex-1 grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-4 min-h-0">
      <!-- MAIN -->
      <main class="bg-white rounded-xl border border-slate-200 flex flex-col min-h-0">
        <div class="px-4 py-3 border-b border-slate-200 flex items-center justify-between">
          <h3 class="text-lg font-semibold text-gray-900">Quote Details</h3>
          <button
            v-if="costLines.length === 0"
            class="inline-flex items-center justify-center h-9 px-3 rounded-md bg-blue-600 text-white border border-blue-700 text-sm font-medium hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            style="min-width: 0"
            @click="onCopyFromEstimate"
            :disabled="isLoading"
            :title="'Copy from Estimate'"
          >
            <Copy class="w-4 h-4 mr-1" /> Copy from Estimate
          </button>
        </div>

        <div class="flex-1 min-h-0 overflow-auto">
          <div v-if="isLoading" class="h-full flex items-center justify-center text-gray-500 gap-2">
            <!-- spinner -->
          </div>
          <template v-else>
            <!-- BUG: @duplicate-line only works for 'material' lines. 'time'/'adjust' silently ignored.
                 Need handleDuplicateLine() that respects original kind. -->
            <SmartCostLinesTable
              v-if="hasCostSetQuote"
              :jobId="jobId"
              :tabKind="'quote'"
              :lines="costLines"
              :readOnly="isLoading || areEditsBlocked"
              :showItemColumn="true"
              :showSourceColumn="false"
              @delete-line="handleSmartDelete"
              @add-line="handleAddEmptyLine"
              @duplicate-line="(line) => handleAddMaterial(line as any)"
              @create-line="handleCreateFromEmpty"
            />
            <div v-else class="text-center py-8 text-gray-500">No quote data available</div>
          </template>
        </div>
      </main>

      <!-- ASIDE -->
      <aside class="space-y-4 lg:sticky lg:top-16 self-start">
        <!-- Summary -->
        <div class="bg-white rounded-xl border border-slate-200">
          <div class="p-3 w-full">
            <CompactSummaryCard
              :key="`quote-summary-compact-${quoteKey}`"
              title="Quote Summary"
              class="w-full"
              :summary="currentQuote.quote?.summary"
              :costLines="costLines"
              :isLoading="isLoading"
              :revision="currentQuote.quote?.rev"
              @expand="showDetailedSummary = true"
            />
          </div>
        </div>

        <!-- Quote Management -->
        <div class="bg-white rounded-xl border border-slate-200">
          <Card class="border-0 shadow-none">
            <CardHeader class="pb-2 flex flex-col items-center">
              <CardTitle>Quote Management</CardTitle>
              <CardDescription>Manage quotes for this job.</CardDescription>
            </CardHeader>

            <CardContent>
              <template v-if="hasXeroQuote">
                <div class="space-y-2">
                  <div class="flex items-center gap-3">
                    <span class="h-8 w-1 rounded bg-blue-500/80"></span>
                    <div>
                      <div class="text-sm uppercase tracking-wide text-slate-500">Quote total</div>
                      <div class="text-1xl font-semibold tabular-nums text-slate-900">
                        {{ formatCurrency(localQuote?.total_excl_tax || 0) }}
                      </div>
                      <div v-if="isQuoteAccepted" class="text-xs text-emerald-700 font-medium">
                        Accepted · {{ formatDate(props.quoteAcceptanceDate!) }}
                      </div>
                    </div>
                  </div>

                  <div class="space-y-2">
                    <div class="flex items-center gap-3">
                      <span class="text-[11px] uppercase tracking-wide text-slate-500">Xero</span>
                      <div class="h-px bg-slate-200 flex-1"></div>
                    </div>
                    <div class="flex flex-wrap gap-2">
                      <Button
                        class="mr-10"
                        variant="outline"
                        size="sm"
                        @click="goToQuoteOnXero"
                        :disabled="!localQuote?.online_url"
                      >
                        <ExternalLink class="h-4 w-4 mr-1" /> Open in Xero
                      </Button>

                      <Button
                        v-if="!isQuoteAccepted"
                        size="sm"
                        class="bg-emerald-600 hover:bg-emerald-700 text-white"
                        :disabled="isAcceptingQuote || !canAcceptQuote"
                        @click="acceptQuote"
                      >
                        <svg
                          v-if="isAcceptingQuote"
                          class="animate-spin h-4 w-4 mr-1"
                          viewBox="0 0 24 24"
                        >
                          <circle
                            class="opacity-25"
                            cx="12"
                            cy="12"
                            r="10"
                            stroke="currentColor"
                            stroke-width="4"
                          />
                        </svg>
                        {{ isAcceptingQuote ? 'Accepting…' : 'Accept Quote' }}
                      </Button>

                      <Button
                        variant="destructive"
                        size="sm"
                        :disabled="isDeletingQuote"
                        @click="deleteQuoteOnXero"
                      >
                        <svg
                          v-if="isDeletingQuote"
                          class="animate-spin h-4 w-4 mr-1"
                          viewBox="0 0 24 24"
                        >
                          <circle
                            class="opacity-25"
                            cx="12"
                            cy="12"
                            r="10"
                            stroke="currentColor"
                            stroke-width="4"
                          />
                        </svg>
                        {{ isDeletingQuote ? 'Deleting…' : 'Delete' }}
                      </Button>
                    </div>
                  </div>

                  <div class="space-y-2">
                    <div class="flex items-center gap-3">
                      <span class="text-[11px] uppercase tracking-wide text-slate-500">Local</span>
                      <div class="h-px bg-slate-200 flex-1"></div>
                    </div>
                    <div class="flex flex-wrap gap-2">
                      <Button
                        class="mr-50"
                        variant="outline"
                        size="sm"
                        @click="onShowQuoteRevisions"
                      >
                        <BookOpen class="h-4 w-4 mr-1" /> Revisions
                      </Button>
                    </div>
                  </div>
                </div>
              </template>

              <template v-else>
                <div class="flex flex-col items-center text-center py-8">
                  <div class="text-gray-500 mb-4">No quotes for this project</div>
                  <button
                    @click="createQuote"
                    :disabled="isCreatingQuote"
                    class="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 flex items-center gap-2"
                  >
                    <svg
                      v-if="isCreatingQuote"
                      class="animate-spin -ml-1 mr-1 h-4 w-4"
                      viewBox="0 0 24 24"
                    >
                      <circle
                        class="opacity-25"
                        cx="12"
                        cy="12"
                        r="10"
                        stroke="currentColor"
                        stroke-width="4"
                      />
                    </svg>
                    {{ isCreatingQuote ? 'Creating...' : 'Create Quote' }}
                  </button>
                  <div class="space-y-2">
                    <div class="flex items-center gap-3">
                      <span class="text-[11px] uppercase tracking-wide text-slate-500">Local</span>
                      <div class="h-px bg-slate-200 flex-1"></div>
                    </div>
                    <div class="flex flex-wrap gap-2">
                      <Button
                        class="mr-50"
                        variant="outline"
                        size="sm"
                        @click="onShowQuoteRevisions"
                      >
                        <BookOpen class="h-4 w-4 mr-1" /> Revisions
                      </Button>
                    </div>
                  </div>
                </div>
              </template>
            </CardContent>
          </Card>
        </div>
      </aside>
    </div>

    <!-- Quote Revisions Modal -->
    <Dialog :open="showQuoteRevisionsModal" @update:open="showQuoteRevisionsModal = $event">
      <DialogContent class="sm:max-w-5xl max-h-[90vh] min-h-[70vh] flex flex-col">
        <DialogHeader class="flex-shrink-0 pb-4">
          <DialogTitle class="text-xl font-semibold">Quote Revisions History</DialogTitle>
          <DialogDescription class="text-muted-foreground">
            View all previous quote revisions and create new ones
          </DialogDescription>
        </DialogHeader>

        <div v-if="isLoading" class="flex-1 flex items-center justify-center">
          <div class="flex flex-col items-center gap-3">
            <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
            <span class="text-sm text-muted-foreground">Loading revisions...</span>
          </div>
        </div>

        <div v-else-if="quoteRevisionsData" class="flex-1 flex flex-col min-h-0 space-y-4">
          <!-- Summary Header -->
          <div class="flex-shrink-0 bg-muted/50 rounded-lg p-4 border">
            <div class="flex items-center justify-between">
              <div>
                <h4 class="font-medium text-foreground mb-1">
                  Job {{ quoteRevisionsData.job_number }}
                </h4>
                <p class="text-sm text-muted-foreground">
                  {{ quoteRevisionsData.total_revisions }} revision{{
                    quoteRevisionsData.total_revisions !== 1 ? 's' : ''
                  }}
                  total
                </p>
              </div>
              <div class="text-right">
                <p class="text-sm text-muted-foreground">Current CostSet Rev</p>
                <p class="font-semibold text-foreground">
                  #{{ quoteRevisionsData.current_cost_set_rev }}
                </p>
              </div>
            </div>
          </div>

          <!-- Create New Revision Button -->
          <div class="flex-shrink-0 flex justify-end">
            <Button @click="onCreateNewRevision" :disabled="isCreatingRevision" size="sm">
              <PlusCircle class="w-4 h-4 mr-2" />
              {{ isCreatingRevision ? 'Creating...' : 'Create New Revision' }}
            </Button>
          </div>

          <!-- Revisions List -->
          <div v-if="quoteRevisions.length > 0" class="flex-1 flex flex-col min-h-0">
            <h5 class="flex-shrink-0 font-medium text-foreground mb-3">Previous Revisions</h5>
            <div class="flex-1 overflow-y-auto space-y-3 pr-2">
              <div
                v-for="revision in quoteRevisions"
                :key="revision.quote_revision"
                class="bg-card border rounded-lg p-4 shadow-sm"
              >
                <!-- HEADER -->
                <div class="flex items-start justify-between mb-3">
                  <div class="flex-1">
                    <div class="flex items-center gap-3">
                      <div class="flex items-center gap-2">
                        <RotateCcw class="w-4 h-4 text-primary" />
                        <span class="font-semibold text-foreground">
                          Revision #{{ revision.quote_revision }}
                        </span>
                      </div>
                      <span class="text-sm text-muted-foreground">
                        {{ revision.archived_at ? formatDate(revision.archived_at) : '—' }}
                      </span>
                    </div>
                  </div>
                </div>
                <!-- /HEADER -->

                <!-- Reason -->
                <div v-if="revision.reason" class="mb-3 p-3 bg-muted/30 rounded-md">
                  <p class="text-sm">
                    <span class="font-medium">Reason:</span> {{ revision.reason }}
                  </p>
                </div>

                <!-- Summary Stats -->
                <div class="grid grid-cols-3 gap-4 text-sm mb-4">
                  <div class="flex flex-col">
                    <span class="text-muted-foreground text-xs uppercase tracking-wide">Cost</span>
                    <span class="font-semibold text-destructive">
                      {{ formatCurrency(revision.summary?.cost ?? 0) }}
                    </span>
                  </div>
                  <div class="flex flex-col">
                    <span class="text-muted-foreground text-xs uppercase tracking-wide"
                      >Revenue</span
                    >
                    <span class="font-semibold text-green-600">
                      {{ formatCurrency(revision.summary?.rev ?? 0) }}
                    </span>
                  </div>
                  <div class="flex flex-col">
                    <span class="text-muted-foreground text-xs uppercase tracking-wide">Hours</span>
                    <span class="font-semibold text-primary">
                      {{ formatNumber(revision.summary?.hours ?? 0) }}h
                    </span>
                  </div>
                </div>

                <!-- Cost Lines -->
                <div class="border-t pt-4">
                  <div class="flex items-center justify-between mb-3">
                    <h6 class="text-sm font-medium text-foreground">
                      Cost Lines ({{ revision.cost_lines.length }})
                    </h6>
                  </div>

                  <div class="space-y-2 max-h-40 overflow-y-auto">
                    <div
                      v-for="line in revision.cost_lines"
                      :key="line.id"
                      class="flex items-center justify-between text-sm bg-muted/30 rounded-md p-3"
                    >
                      <div class="flex-1 min-w-0">
                        <div class="flex items-center gap-2">
                          <Badge
                            variant="secondary"
                            class="text-xs"
                            :class="
                              line.kind === 'time'
                                ? 'bg-blue-100 text-blue-800'
                                : line.kind === 'material'
                                  ? 'bg-purple-100 text-purple-800'
                                  : 'bg-orange-100 text-orange-800'
                            "
                          >
                            {{ line.kind }}
                          </Badge>
                          <span class="font-medium text-foreground truncate">
                            {{ line.desc || 'Untitled line' }}
                          </span>
                        </div>
                      </div>

                      <div class="flex items-center gap-4 text-right flex-shrink-0">
                        <div class="text-center">
                          <div class="text-xs text-muted-foreground uppercase tracking-wide">
                            Qty
                          </div>
                          <div class="font-medium">{{ formatNumber(line.quantity ?? 0) }}</div>
                        </div>
                        <div class="text-center">
                          <div class="text-xs text-muted-foreground uppercase tracking-wide">
                            Cost
                          </div>
                          <div class="font-medium text-destructive">
                            {{ formatCurrency(line.total_cost ?? 0) }}
                          </div>
                        </div>
                        <div class="text-center">
                          <div class="text-xs text-muted-foreground uppercase tracking-wide">
                            Rev
                          </div>
                          <div class="font-medium text-green-600">
                            {{ formatCurrency(line.total_rev ?? 0) }}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div v-else class="flex-1 flex items-center justify-center">
          <div class="text-center">
            <FileX class="w-12 h-12 text-muted-foreground/50 mx-auto mb-4" />
            <p class="text-muted-foreground">No previous revisions found</p>
            <p class="text-sm text-muted-foreground/70 mt-1">
              Create your first revision to get started
            </p>
          </div>
        </div>

        <DialogFooter class="flex-shrink-0 pt-4 border-t">
          <Button variant="outline" @click="showQuoteRevisionsModal = false"> Close </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Detailed Summary Dialog -->
    <Dialog :open="showDetailedSummary" @update:open="showDetailedSummary = $event">
      <DialogContent class="sm:max-w-4xl max-h-[80vh]">
        <DialogHeader>
          <DialogTitle>Detailed Quote Summary</DialogTitle>
          <DialogDescription>Complete breakdown of quote costs and revenue</DialogDescription>
        </DialogHeader>
        <div class="max-h-[60vh] overflow-y-auto">
          <CostSetSummaryCard
            :key="`quote-summary-detailed-${quoteKey}`"
            title="Quote Summary"
            :summary="currentQuote.quote?.summary"
            :costLines="costLines"
            :isLoading="isLoading"
            :revision="currentQuote.quote?.rev"
          />
        </div>
        <DialogFooter>
          <Button variant="outline" @click="showDetailedSummary = false">Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Xero Export Options Modal -->
    <Dialog :open="showXeroExportModal" @update:open="showXeroExportModal = $event">
      <DialogContent class="sm:max-w-md" @keydown.enter.prevent="executeCreateQuote(false)">
        <DialogHeader>
          <DialogTitle>Export Quote to Xero</DialogTitle>
          <DialogDescription> Choose how you want to export this quote to Xero </DialogDescription>
        </DialogHeader>
        <div class="space-y-4 py-4">
          <div class="space-y-3">
            <Button
              class="w-full h-auto py-4 px-4 flex flex-col items-start gap-1"
              variant="default"
              @click="executeCreateQuote(false)"
            >
              <span class="font-semibold">Send Total Only</span>
              <span class="text-xs font-normal opacity-90">
                Export as a single line item with the total amount (Default)
              </span>
            </Button>
            <Button
              class="w-full h-auto py-4 px-4 flex flex-col items-start gap-1"
              variant="outline"
              @click="executeCreateQuote(true)"
            >
              <span class="font-semibold">Send Breakdown</span>
              <span class="text-xs font-normal opacity-70">
                Export with all individual line items
              </span>
            </Button>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" @click="showXeroExportModal = false">Cancel</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '../../utils/debug'
import { toLocalDateString } from '../../utils/dateUtils'

import { ref, computed, watch, onMounted } from 'vue'
import { BookOpen, PlusCircle, RotateCcw, FileX, Copy, ExternalLink } from 'lucide-vue-next'
import SmartCostLinesTable from '../shared/SmartCostLinesTable.vue'
import CostSetSummaryCard from '../shared/CostSetSummaryCard.vue'
import { toast } from 'vue-sonner'
import { formatCurrency } from '@/utils/string-formatting'
import { schemas } from '../../api/generated/api'
import { api } from '../../api/client'
import type { AxiosError } from 'axios'
import { z } from 'zod'
import { costlineService } from '../../services/costline.service'
import { fetchCostSet } from '../../services/costing.service'
import { useCostLinesActions } from '../../composables/useCostLinesActions'
import CompactSummaryCard from '../shared/CompactSummaryCard.vue'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../../components/ui/dialog'
import { Button } from '../../components/ui/button'
import { Badge } from '../../components/ui/badge'
import { Card, CardHeader, CardContent, CardDescription, CardTitle } from '../ui/card'

type CostLine = z.infer<typeof schemas.CostLine>
type CostSet = z.infer<typeof schemas.CostSet>
type QuoteRevisionsListResponse = z.infer<typeof schemas.QuoteRevisionsList>
type Quote = z.infer<typeof schemas.Quote>
type JobQuoteAcceptancePayload = z.input<typeof schemas.JobQuoteAcceptanceRequest>

const props = defineProps<{
  jobId: string
  jobNumber: string
  jobStatus: string
  pricingMethodology: string
  quoted: boolean
  fullyInvoiced: boolean
  quoteAcceptanceDate?: string | null
}>()

const emit = defineEmits<{
  'cost-line-changed': []
}>()

const quoteCostSet = ref<CostSet | null>(null)
const xeroQuote = ref<Quote | null>(null)

// Fetch quote cost set on mount
onMounted(async () => {
  if (props.jobId) {
    try {
      const response = await fetchCostSet(props.jobId, 'quote')
      quoteCostSet.value = response

      // Try to load Xero quote if available
      try {
        const xeroQuoteResponse: Quote = await api.job_rest_jobs_quote_retrieve({
          params: { job_id: props.jobId },
        })
        xeroQuote.value = xeroQuoteResponse
      } catch {
        // Xero quote not available, that's ok
        xeroQuote.value = null
      }
    } catch (error) {
      toast.error('Failed to load quote data')
      console.error('Failed to load quote data:', error)
    }
  }
})

const currentQuote = computed(() => {
  const costSet = quoteCostSet.value

  if (!costSet) {
    return { has_quote: false, quote: null }
  }

  // Use API structure exactly as returned - NO CONVERSIONS
  return {
    has_quote: true,
    quote: {
      id: costSet.id,
      kind: costSet.kind,
      rev: costSet.rev,
      created: costSet.created,
      summary: costSet.summary,
      cost_lines: costSet.cost_lines || [],
    },
  }
})

const isLoading = ref(false)
const showQuoteRevisionsModal = ref(false)
const quoteRevisionsData = ref<QuoteRevisionsListResponse | null>(null)
const isCreatingRevision = ref(false)
const costLines = ref<CostLine[]>([])
const quoteKey = ref(0) // Force reactivity key
const showDetailedSummary = ref(false)

// Quote management state
const isCreatingQuote = ref(false)
const isQuoteDeleted = ref(false)
const isDeletingQuote = ref(false)
const isAcceptingQuote = ref(false)
const showXeroExportModal = ref(false)

const hasCostSetQuote = computed(
  () => !!(currentQuote.value?.has_quote && currentQuote.value.quote),
)
const hasXeroQuote = computed(() => !!xeroQuote.value)
const isQuoteAccepted = computed(() => !!props.quoteAcceptanceDate)
const canAcceptQuote = computed(() => {
  // Button should only be enabled if status is draft or awaiting_approval
  return props.jobStatus === 'draft' || props.jobStatus === 'awaiting_approval'
})
const localQuote = computed(() => xeroQuote.value) // Xero

// Check if estimate data is available for copying
const hasEstimateData = ref(false)

// Load estimate data availability on mount
onMounted(async () => {
  if (props.jobId) {
    try {
      const estimateResponse = await fetchCostSet(props.jobId, 'estimate')
      hasEstimateData.value = !!estimateResponse?.cost_lines?.length
    } catch {
      hasEstimateData.value = false
    }
  }
})

// Check if there are any quote revisions available
type QuoteRevisionSummary = z.infer<typeof schemas.JobCostSetSummary>
type QuoteRevisionListItem = {
  quote_revision: number
  archived_at: string | null
  reason: string | null
  summary: QuoteRevisionSummary | null
  cost_lines: CostLine[]
}

const quoteRevisions = computed<QuoteRevisionListItem[]>(() => {
  const revisions = quoteRevisionsData.value?.revisions ?? []

  return revisions.map((revision) => {
    const summaryResult = schemas.JobCostSetSummary.safeParse(revision.summary)
    const summary = summaryResult.success ? summaryResult.data : null

    const parsedLines: CostLine[] = []
    if (Array.isArray(revision.cost_lines)) {
      for (const line of revision.cost_lines) {
        const parsedLine = schemas.CostLine.safeParse(line)
        if (parsedLine.success) {
          parsedLines.push(parsedLine.data)
        }
      }
    }

    return {
      quote_revision: typeof revision.quote_revision === 'number' ? revision.quote_revision : 0,
      archived_at: typeof revision.archived_at === 'string' ? revision.archived_at : null,
      reason: typeof revision.reason === 'string' ? revision.reason : null,
      summary,
      cost_lines: parsedLines,
    }
  })
})

const hasQuoteRevisions = computed(() => {
  if (!quoteRevisionsData.value) return false
  return quoteRevisionsData.value.total_revisions > 0
})

// Edits are blocked if quote is accepted AND there are no revisions to unlock it
const areEditsBlocked = computed(() => {
  return !!props.quoteAcceptanceDate && !hasQuoteRevisions.value
})

watch(
  () => currentQuote.value.quote?.cost_lines,
  (lines) => {
    if (lines) costLines.value = lines
  },
  { immediate: true },
)

// Watch for quote acceptance to fetch revisions data
watch(
  () => props.quoteAcceptanceDate,
  (acceptanceDate) => {
    if (acceptanceDate && currentQuote.value?.has_quote) {
      // When a quote gets accepted, fetch revisions to check if edits should be blocked
      fetchQuoteRevisions()
    }
  },
  { immediate: true },
)

async function refreshQuoteData() {
  if (!props.jobId) return
  isLoading.value = true

  // DEBUG: Log before refresh
  debugLog('REFRESH QUOTE - BEFORE:')
  debugLog('  - Current quote rev:', currentQuote.value?.quote?.rev)
  debugLog('  - Current cost lines count:', costLines.value.length)

  try {
    const response = await fetchCostSet(props.jobId, 'quote')

    // Update our local quote cost set
    quoteCostSet.value = response

    if (response.cost_lines && Array.isArray(response.cost_lines)) {
      costLines.value = response.cost_lines
    } else {
      costLines.value = []
    }

    // Refresh Xero quote data
    try {
      const xeroQuoteResponse: Quote = await api.job_rest_jobs_quote_retrieve({
        params: { job_id: props.jobId },
      })
      xeroQuote.value = xeroQuoteResponse
    } catch {
      // Xero quote not available, that's ok
      xeroQuote.value = null
    }
  } catch (error) {
    toast.error('Failed to refresh quote data')
    console.error('Failed to refresh quote data:', error)
    console.error('🔍 REFRESH QUOTE DEBUG - ERROR:', error)
  } finally {
    isLoading.value = false
  }
}

function onShowQuoteRevisions() {
  showQuoteRevisionsModal.value = true
  fetchQuoteRevisions()
}

async function fetchQuoteRevisions() {
  if (!props.jobId) return

  isLoading.value = true
  try {
    const response = await api.job_rest_jobs_cost_sets_quote_revise_retrieve({
      params: { job_id: props.jobId },
    })

    quoteRevisionsData.value = response
  } catch (error) {
    toast.error('Failed to fetch quote revisions')
    console.error('Failed to fetch quote revisions:', error)
    console.error('🔍 FETCH REVISIONS DEBUG - ERROR:', error)
  } finally {
    isLoading.value = false
  }
}

async function onCreateNewRevision() {
  if (!props.jobId) return
  console.log('onCreateNewRevision jobId:', props.jobId)
  isCreatingRevision.value = true
  toast.info('Creating new quote revision...', { id: 'create-revision' })
  try {
    const response = await api.job_rest_jobs_cost_sets_quote_revise_create(
      { reason: 'Manual revision creation' },
      {
        params: { job_id: props.jobId },
      },
    )

    if (response.success) {
      toast.success(`Quote revision ${response.quote_revision} created successfully!`)
      // Force reactivity update
      quoteKey.value++
      // Refresh data
      await Promise.all([fetchQuoteRevisions(), refreshQuoteData()])
    } else {
      toast.error('Failed to create quote revision')
    }
  } catch (error) {
    toast.error('Error creating quote revision')
    console.error('Error creating quote revision:', error)
  } finally {
    isCreatingRevision.value = false
    toast.dismiss('create-revision')
  }
}

const { handleAddMaterial, handleSmartDelete, handleAddEmptyLine, handleCreateFromEmpty } =
  useCostLinesActions({
    costLines,
    jobId: props.jobId,
    costSetKind: 'quote',
    isLoading,
    onCostLinesChanged: async () => {
      // Refresh quote data to update summary from API
      emit('cost-line-changed')
      await refreshQuoteData()
    },
  })

// --- QUOTE METHODS ---
const createQuote = () => {
  // Show modal to ask user if they want breakdown or total
  showXeroExportModal.value = true
}

const executeCreateQuote = async (breakdown: boolean) => {
  if (!props.jobId || isCreatingQuote.value) return
  isCreatingQuote.value = true
  showXeroExportModal.value = false
  try {
    const response = await api.api_xero_create_quote_create(
      { breakdown },
      {
        params: { job_id: props.jobId },
      },
    )
    if (!response.success) {
      const msgs = response.messages?.length ? response.messages : ['Failed to create quote']
      msgs.forEach((msg) => toast.error(msg))
      return
    }
    toast.success('Quote created successfully!')
    if (response.messages?.length) {
      response.messages.forEach((msg) => toast.warning(msg))
    }
    isQuoteDeleted.value = false
    await refreshQuoteData()
    emit('cost-line-changed')
  } catch (err: unknown) {
    debugLog('Error creating quote:', err)
    let msg = 'Unexpected error while trying to create quote.'
    if ((err as AxiosError).isAxiosError) {
      const axiosErr = err as AxiosError<{ message: string }>
      msg = axiosErr.response?.data?.message ?? msg
    }
    toast.error(`Failed to create quote: ${msg}`)
  } finally {
    isCreatingQuote.value = false
  }
}

const acceptQuote = async () => {
  if (!props.jobId || isAcceptingQuote.value) return
  isAcceptingQuote.value = true
  try {
    const acceptancePayload: JobQuoteAcceptancePayload = {
      success: true,
      job_id: props.jobId,
      quote_acceptance_date: new Date().toISOString(),
      message: 'Quote accepted via frontend',
    }
    const response = await api.job_rest_jobs_quote_accept_create(acceptancePayload, {
      params: { job_id: props.jobId },
    })
    if (response.success) {
      toast.success('Quote accepted successfully!')
      await refreshQuoteData()
      emit('cost-line-changed')
    } else {
      toast.error('Failed to accept quote')
    }
  } catch (err) {
    console.error('Error accepting quote:', err)
    toast.error('Failed to accept quote.')
  } finally {
    isAcceptingQuote.value = false
  }
}

const goToQuoteOnXero = () => {
  if (xeroQuote.value?.online_url && xeroQuote.value.online_url !== '#') {
    window.open(xeroQuote.value.online_url, '_blank')
  }
}

const deleteQuoteOnXero = async () => {
  if (!props.jobId || isDeletingQuote.value) return
  isDeletingQuote.value = true
  try {
    const response = await api.api_xero_delete_quote_destroy(undefined, {
      params: { job_id: props.jobId },
    })
    if (!response.success) {
      const msgs = response.messages?.length ? response.messages : ['Failed to delete quote']
      msgs.forEach((msg) => toast.error(msg))
      return
    }
    isQuoteDeleted.value = true
    toast.success('Quote deleted successfully!')
    if (response.messages?.length) {
      response.messages.forEach((msg) => toast.warning(msg))
    }
    await refreshQuoteData()
    emit('cost-line-changed')
  } catch (err: unknown) {
    debugLog('Error deleting quote:', err)
    let msg = 'Unexpected error while trying to delete quote.'
    if ((err as AxiosError).isAxiosError) {
      const axiosErr = err as AxiosError<{ message: string }>
      msg = axiosErr.response?.data?.message ?? msg
    }
    toast.error(`Failed to delete quote: ${msg}`)
  } finally {
    isDeletingQuote.value = false
  }
}

function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-NZ', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value)
}

function formatDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString('en-NZ', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

// Copy all cost lines from estimate to quote
async function onCopyFromEstimate() {
  if (!hasEstimateData.value) {
    toast.error('No estimate data available to copy')
    return
  }

  isLoading.value = true
  toast.info('Copying from estimate...', { id: 'copy-estimate' })

  try {
    // Fetch estimate data
    const estimateResponse = await fetchCostSet(props.jobId, 'estimate')

    if (!estimateResponse?.cost_lines?.length) {
      toast.error('No estimate data available to copy')
      return
    }

    const estimateLines = estimateResponse.cost_lines

    // Clear existing quote lines first
    if (costLines.value.length > 0) {
      await Promise.allSettled(
        costLines.value.filter((l) => l.id).map((line) => costlineService.deleteCostLine(line.id)),
      )
    }

    // Copy each estimate line to quote
    const createdLines: CostLine[] = []
    for (const estimateLine of estimateLines) {
      const createPayload = {
        kind: estimateLine.kind as 'material' | 'time' | 'adjust',
        desc: estimateLine.desc || '',
        quantity: estimateLine.quantity || 0,
        unit_cost: estimateLine.unit_cost ?? 0,
        unit_rev: estimateLine.unit_rev ?? 0,
        accounting_date: estimateLine.accounting_date || toLocalDateString(),
        ext_refs: (estimateLine.ext_refs as Record<string, unknown>) || {},
        meta: (estimateLine.meta as Record<string, unknown>) || {},
      }

      const created = await costlineService.createCostLine(props.jobId, 'quote', createPayload)
      createdLines.push(created)
    }

    // Update local state temporarily until refresh completes
    costLines.value = createdLines

    // Refresh quote data to get updated summary (will fetch full CostLine objects)
    await refreshQuoteData()

    toast.success(`Copied ${createdLines.length} lines from estimate!`)
    emit('cost-line-changed')
  } catch (error) {
    toast.error('Failed to copy from estimate.')
    console.error('Failed to copy from estimate:', error)
  } finally {
    isLoading.value = false
    toast.dismiss('copy-estimate')
  }
}

onMounted(() => {
  console.log('[QUOTE-TAB]: Props ', {
    jobId: props.jobId,
    jobNumber: props.jobNumber,
    pricingMethodology: props.pricingMethodology,
    quoted: props.quoted,
    fullyInvoiced: props.fullyInvoiced,
  })
})
</script>
