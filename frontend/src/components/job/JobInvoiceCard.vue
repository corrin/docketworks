<template>
  <aside class="bg-white rounded-xl border border-slate-200">
    <Card class="border-0 shadow-none overflow-hidden">
      <CardHeader class="px-3 pt-3 pb-2">
        <CardTitle>
          Invoices <span class="text-slate-400 text-sm">({{ invoices.length }})</span>
        </CardTitle>
        <CardDescription>Manage invoices for this job.</CardDescription>
      </CardHeader>

      <CardContent class="p-0 pb-2">
        <div class="max-h-[20rem] overflow-y-auto px-2" style="scrollbar-gutter: stable">
          <div v-if="invoices.length === 0" class="text-center py-6 text-gray-500">
            No invoices for this project
          </div>

          <ul
            v-else
            role="list"
            data-automation-id="JobInvoiceCard-list"
            class="divide-y divide-slate-200 rounded-md bg-white"
          >
            <li
              v-for="invoice in invoices"
              :key="invoice.id"
              class="px-3 py-1.5 hover:bg-slate-50 flex items-center gap-3"
            >
              <div class="min-w-0 flex-1">
                <div class="flex items-center gap-2">
                  <span class="font-medium text-slate-900 text-sm leading-5">
                    {{ invoice.number }}
                  </span>
                  <Badge
                    :variant="invoice.status === 'PAID' ? 'default' : 'secondary'"
                    class="text-[10px] px-1.5 py-0.5 rounded-full"
                  >
                    {{ invoice.status }}
                  </Badge>
                </div>
                <div class="text-[11px] leading-4 text-slate-500">
                  {{ formatDate(invoice.date) }}
                </div>
              </div>

              <div class="shrink-0 text-sm font-semibold tabular-nums text-slate-900">
                {{ formatCurrency(invoice.total_excl_tax) }}
              </div>

              <div class="shrink-0 flex items-center gap-2">
                <Button
                  variant="outline"
                  size="icon"
                  class="h-7 w-7"
                  :data-automation-id="`JobInvoiceCard-open-${invoice.id}`"
                  :aria-label="`Open invoice ${invoice.number} in Xero`"
                  @click="goToInvoiceOnXero(invoice.online_url)"
                  :disabled="!invoice.online_url"
                >
                  <ExternalLink class="h-4 w-4" />
                </Button>
                <Button
                  variant="destructive"
                  size="icon"
                  class="h-7 w-7"
                  :data-automation-id="`JobInvoiceCard-delete-${invoice.id}`"
                  :aria-label="`Delete invoice ${invoice.number}`"
                  @click="deleteInvoiceOnXero(invoice.xero_id)"
                  :disabled="!!deletingInvoiceId"
                >
                  <svg
                    v-if="deletingInvoiceId === invoice.xero_id"
                    class="animate-spin h-4 w-4"
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
                    <path
                      class="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                    />
                  </svg>
                  <Trash2 v-else class="h-4 w-4" />
                </Button>
              </div>
            </li>
          </ul>
        </div>
      </CardContent>

      <div>
        <div class="border-t border-slate-200"></div>
        <CardFooter class="flex flex-col items-center gap-2 pt-4">
          <button
            v-if="props.remainingToInvoice > 0"
            data-automation-id="JobFinishTab-create-invoice"
            @click="openInvoiceModal()"
            :disabled="isCreatingInvoice || !!props.paid || !xeroConnected"
            class="px-4 py-2 bg-orange-600 text-white rounded-md hover:bg-orange-700 focus:outline-none focus:ring-2 focus:ring-orange-500 disabled:opacity-50 flex items-center gap-2"
          >
            <svg
              v-if="isCreatingInvoice"
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
              <path
                class="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            {{ isCreatingInvoice ? 'Creating...' : invoiceButtonText }}
          </button>

          <p
            v-else
            data-automation-id="JobFinishTab-fully-invoiced"
            class="text-xs text-slate-500 text-center"
          >
            Fully invoiced — nothing further to invoice.
          </p>

          <p v-if="props.paid" class="text-xs text-slate-500 text-center">
            Job is marked as <strong>Paid</strong>. Unmark "Paid" to create another invoice.
          </p>
        </CardFooter>
      </div>
    </Card>

    <Dialog :open="showInvoiceModal" @update:open="showInvoiceModal = $event">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Create Invoice</DialogTitle>
          <DialogDescription>{{ invoiceModalDescription }}</DialogDescription>
        </DialogHeader>
        <div class="space-y-4 py-4">
          <div class="rounded-lg bg-slate-50 p-3 text-sm space-y-1">
            <div class="flex justify-between border-t pt-1">
              <span class="text-slate-700 font-medium">Current amount to invoice</span>
              <span class="font-bold text-orange-600 tabular-nums">
                {{ formatCurrency(props.remainingToInvoice) }}
              </span>
            </div>
          </div>

          <div class="space-y-3">
            <template v-if="props.pricingMethodology === 'fixed_price'">
              <Button
                class="w-full h-auto py-4 px-4 flex flex-col items-start gap-1"
                variant="default"
                data-automation-id="JobFinishTab-mode-invoice-full"
                @click="executeCreateInvoice('invoice_full')"
                :disabled="isCreatingInvoice"
              >
                <span class="font-semibold">{{ fullInvoiceLabel }}</span>
                <span class="text-xs font-normal opacity-90">
                  {{ formatCurrency(props.remainingToInvoice) }} excl GST
                </span>
              </Button>

              <Button
                class="w-full h-auto py-4 px-4 flex flex-col items-start gap-1"
                variant="outline"
                data-automation-id="JobFinishTab-mode-invoice-percent"
                @click="selectInvoiceMode('invoice_percent')"
                :disabled="isCreatingInvoice"
              >
                <span class="font-semibold">Invoice % of quote</span>
                <span class="text-xs font-normal opacity-70">
                  Invoice a cumulative percentage of the quoted amount
                </span>
              </Button>
              <div v-if="selectedInvoiceMode === 'invoice_percent'" class="flex gap-2">
                <Input
                  v-model="invoicePercentInput"
                  type="number"
                  min="1"
                  max="100"
                  step="0.1"
                  placeholder="e.g. 50"
                  @keydown.enter.prevent="executeCreateInvoice('invoice_percent')"
                />
                <Button
                  @click="executeCreateInvoice('invoice_percent')"
                  size="sm"
                  :disabled="isCreatingInvoice"
                >
                  Confirm
                </Button>
              </div>
            </template>

            <template v-else>
              <Button
                class="w-full h-auto py-4 px-4 flex flex-col items-start gap-1"
                variant="default"
                data-automation-id="JobFinishTab-mode-invoice-costs-to-date"
                @click="executeCreateInvoice('invoice_costs_to_date')"
                :disabled="isCreatingInvoice"
              >
                <span class="font-semibold">{{ costsToDateLabel }}</span>
                <span class="text-xs font-normal opacity-90">
                  {{ formatCurrency(props.remainingToInvoice) }} excl GST
                </span>
              </Button>
            </template>

            <Button
              class="w-full h-auto py-4 px-4 flex flex-col items-start gap-1"
              variant="outline"
              data-automation-id="JobFinishTab-mode-invoice-amount"
              @click="selectInvoiceMode('invoice_amount')"
              :disabled="isCreatingInvoice"
            >
              <span class="font-semibold">Invoice $ amount</span>
              <span class="text-xs font-normal opacity-70">{{ customAmountHint }}</span>
            </Button>
            <div v-if="selectedInvoiceMode === 'invoice_amount'" class="flex gap-2">
              <Input
                v-model="invoiceAmountInput"
                type="number"
                min="0"
                step="0.01"
                placeholder="0.00"
                @keydown.enter.prevent="executeCreateInvoice('invoice_amount')"
              />
              <Button
                @click="executeCreateInvoice('invoice_amount')"
                size="sm"
                :disabled="isCreatingInvoice"
              >
                Confirm
              </Button>
            </div>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" @click="showInvoiceModal = false" :disabled="isCreatingInvoice">
            Cancel
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </aside>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { toast } from 'vue-sonner'
import debug from 'debug'
import { ExternalLink, Trash2 } from 'lucide-vue-next'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { formatCurrency, formatDate } from '@/utils/string-formatting'
import { useXeroConnection } from '@/composables/useXeroConnection'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '../ui/dialog'
import { Button } from '../ui/button'
import { Card, CardHeader, CardFooter, CardContent, CardDescription, CardTitle } from '../ui/card'
import { Input } from '../ui/input'
import { Badge } from '../ui/badge'
import { isAxiosError } from 'axios'
import { z } from 'zod'

const log = debug('job:invoice')

type Invoice = z.infer<typeof schemas.Invoice>
type XeroInvoiceCreateRequest = z.infer<typeof schemas.XeroInvoiceCreateRequest>
type XeroInvoiceCreateMode = XeroInvoiceCreateRequest['mode']

// Job statuses that mean the work itself is done. Purely a wording choice —
// invoicing stays available at every status.
const COMPLETED_STATUSES = ['recently_completed', 'archived']

const props = defineProps<{
  jobId: string
  pricingMethodology: string
  remainingToInvoice: number
  jobStatus?: string
  paid?: boolean
}>()

const emit = defineEmits<{ 'invoices-changed': [] }>()

const invoices = ref<Array<Invoice>>([])
const isCreatingInvoice = ref(false)
const deletingInvoiceId = ref<string | null>(null)
const { xeroConnected } = useXeroConnection()

const showInvoiceModal = ref(false)
const selectedInvoiceMode = ref<XeroInvoiceCreateMode | null>(null)
const invoicePercentInput = ref('')
const invoiceAmountInput = ref('')

async function loadInvoices() {
  const response = await api.job_jobs_invoices_retrieve({ params: { job_id: props.jobId } })
  invoices.value = response.invoices || []
}

onMounted(async () => {
  try {
    await loadInvoices()
  } catch (error) {
    log('Failed to load invoices: %o', error)
    toast.error('Failed to load invoices')
  }
})

const invoiceButtonText = computed(() =>
  xeroConnected.value ? 'Create Invoice' : 'Login to Xero first',
)

const workComplete = computed(() => COMPLETED_STATUSES.includes(props.jobStatus ?? ''))

const invoiceModalDescription = computed(() => {
  if (!workComplete.value) {
    return 'Request payment in advance, take a deposit, or raise a progress invoice.'
  }
  return props.pricingMethodology === 'fixed_price'
    ? 'Invoice the remaining quote balance.'
    : 'Invoice the remaining Time & Materials costs.'
})

const fullInvoiceLabel = computed(() =>
  workComplete.value ? 'Invoice remaining quote balance' : 'Invoice full amount in advance',
)

const costsToDateLabel = computed(() =>
  workComplete.value ? 'Invoice remaining T&M costs' : 'Invoice costs to date',
)

const customAmountHint = computed(() =>
  workComplete.value
    ? 'Invoice a specific dollar amount'
    : 'Invoice a deposit or progress payment of a specific amount',
)

function openInvoiceModal() {
  selectedInvoiceMode.value = null
  invoicePercentInput.value = ''
  invoiceAmountInput.value = ''
  showInvoiceModal.value = true
}

function selectInvoiceMode(mode: XeroInvoiceCreateMode) {
  selectedInvoiceMode.value = mode
  invoicePercentInput.value = ''
  invoiceAmountInput.value = ''
}

async function executeCreateInvoice(mode: XeroInvoiceCreateMode) {
  if (!props.jobId || isCreatingInvoice.value) return

  let percent: number | undefined
  let amount: number | undefined

  if (mode === 'invoice_percent') {
    const pct = parseFloat(invoicePercentInput.value)
    if (isNaN(pct) || pct <= 0 || pct > 100) {
      toast.error('Please enter a valid percentage (1-100)')
      return
    }
    percent = pct
  }

  if (mode === 'invoice_amount') {
    const amt = parseFloat(invoiceAmountInput.value)
    if (isNaN(amt) || amt <= 0) {
      toast.error('Please enter a valid amount')
      return
    }
    amount = amt
  }

  showInvoiceModal.value = false
  isCreatingInvoice.value = true

  try {
    const body: XeroInvoiceCreateRequest = {
      mode,
      ...(percent !== undefined && { percent }),
      ...(amount !== undefined && { amount }),
    }

    const response = await api.xero_create_invoice_create(body, {
      params: { job_id: props.jobId },
    })
    if (!response?.success) {
      const msgs = response?.messages?.length ? response.messages : ['Failed to create invoice']
      msgs.forEach((msg: string) => toast.error(msg))
      return
    }
    toast.success('Invoice created successfully!')
    if (response.messages?.length) {
      response.messages.forEach((msg: string) => toast.warning(msg))
    }
    await afterInvoiceChange()
  } catch (err: unknown) {
    let msg = 'Unexpected error while trying to create invoice.'
    log('Error creating invoice: %o', err)
    // The payload is typed with the property this code actually reads, so the
    // declared shape and the access below cannot drift apart.
    if (isAxiosError<{ error?: string }>(err) && err.response?.data?.error) {
      msg = err.response.data.error
    }
    toast.error(`Failed to create invoice: ${msg}`)
  } finally {
    isCreatingInvoice.value = false
  }
}

const goToInvoiceOnXero = (url: string | null | undefined) => {
  if (url && url !== '#') {
    window.open(url, '_blank')
  } else {
    toast.error('No online URL available for this invoice.')
  }
}

const deleteInvoiceOnXero = async (invoiceXeroId: string) => {
  if (!props.jobId || deletingInvoiceId.value) return
  deletingInvoiceId.value = invoiceXeroId
  try {
    await api.xero_delete_invoice_destroy(undefined, {
      params: { job_id: props.jobId },
      queries: { xero_invoice_id: invoiceXeroId },
    })
    toast.success('Invoice deleted successfully!')
    await afterInvoiceChange()
  } catch (err) {
    log('Error deleting invoice: %o', err)
    toast.error('Failed to delete invoice.')
  } finally {
    deletingInvoiceId.value = null
  }
}

// The balance is only correct against the current invoice set, so the parent
// re-reads it from the server rather than adjusting it locally.
async function afterInvoiceChange() {
  emit('invoices-changed')
  try {
    await loadInvoices()
  } catch (error) {
    log('Failed to reload invoices: %o', error)
    toast.error('Invoice saved, but the list could not be refreshed. Reload the job.')
  }
}
</script>
