<template>
  <div class="space-y-6">
    <div class="bg-white p-4 rounded-lg border border-gray-200">
      <h2 class="text-lg font-semibold text-gray-900">Finish Job</h2>
      <p class="text-sm text-gray-500">
        Invoice the customer, confirm the job is complete, and review how it performed
      </p>
    </div>

    <div v-if="loading" class="flex items-center justify-center py-12">
      <div class="text-center">
        <div
          class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600 mx-auto mb-2"
        ></div>
        <p class="text-gray-500">Loading job financials...</p>
      </div>
    </div>

    <template v-else>
      <div class="grid grid-cols-1 lg:grid-cols-[1fr_360px] gap-4 items-start">
        <!-- CUSTOMER BALANCE: the counter question -->
        <section
          data-automation-id="JobFinishTab-balance"
          class="bg-white rounded-xl border border-slate-200 p-4"
        >
          <h3 class="text-base font-semibold text-gray-900">Customer balance</h3>
          <p class="text-xs text-slate-500 mb-3">{{ basisDescription }}</p>

          <dl class="space-y-1.5 text-sm">
            <div class="flex justify-between">
              <dt class="text-slate-600">{{ jobValueLabel }}</dt>
              <dd class="tabular-nums font-medium">
                {{ formatCurrency(summary.job_value_excl_gst) }}
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-600">Already invoiced (excl GST)</dt>
              <dd class="tabular-nums font-medium">
                {{ formatCurrency(summary.valid_invoiced_excl_gst) }}
              </dd>
            </div>

            <div class="border-t border-slate-200 pt-1.5 flex justify-between">
              <dt class="text-slate-600">Still to invoice (excl GST)</dt>
              <dd
                data-automation-id="JobFinishTab-remaining-excl-gst"
                class="tabular-nums font-medium"
              >
                {{ formatCurrency(summary.remaining_to_invoice_excl_gst) }}
              </dd>
            </div>
            <div class="flex justify-between">
              <dt class="text-slate-600">GST</dt>
              <dd data-automation-id="JobFinishTab-remaining-gst" class="tabular-nums font-medium">
                {{ formatCurrency(summary.remaining_gst) }}
              </dd>
            </div>
            <div v-if="summary.outstanding_invoiced_incl_gst > 0" class="flex justify-between">
              <dt class="text-slate-600">Unpaid invoices (incl GST)</dt>
              <dd
                data-automation-id="JobFinishTab-outstanding-incl-gst"
                class="tabular-nums font-medium"
              >
                {{ formatCurrency(summary.outstanding_invoiced_incl_gst) }}
              </dd>
            </div>

            <div class="border-t-2 border-slate-300 pt-2 mt-1 flex justify-between items-baseline">
              <dt class="font-semibold text-slate-900">Total to pay</dt>
              <dd
                data-automation-id="JobFinishTab-total-to-pay"
                class="tabular-nums text-2xl font-bold text-emerald-700"
              >
                {{ formatCurrency(summary.total_to_pay_incl_gst) }}
              </dd>
            </div>
          </dl>

          <p
            v-if="summary.total_to_pay_incl_gst === 0"
            data-automation-id="JobFinishTab-nothing-to-pay"
            class="mt-3 text-sm text-slate-600"
          >
            Nothing left to pay. This job is fully invoiced and settled.
          </p>

          <div
            v-if="summary.over_invoiced_excl_gst > 0"
            data-automation-id="JobFinishTab-over-invoiced"
            class="mt-3 rounded-md bg-amber-50 border border-amber-200 p-3 text-sm text-amber-900"
          >
            <strong>Over-invoiced by {{ formatCurrency(summary.over_invoiced_excl_gst) }}</strong>
            (excl GST). This job has been invoiced for more than it is worth. Resolve it with a
            credit note in Xero.
          </div>
        </section>

        <!-- INVOICES -->
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

                <ul v-else role="list" class="divide-y divide-slate-200 rounded-md bg-white">
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
                        @click="goToInvoiceOnXero(invoice.online_url)"
                        :disabled="!invoice.online_url"
                      >
                        <ExternalLink class="h-4 w-4" />
                      </Button>
                      <Button
                        variant="destructive"
                        size="icon"
                        class="h-7 w-7"
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
                  v-if="canInvoiceFurther"
                  data-automation-id="JobFinishTab-create-invoice"
                  @click="createInvoice()"
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
        </aside>
      </div>

      <!-- COMPLETION CHECKLIST -->
      <section
        data-automation-id="JobFinishTab-checklist"
        class="bg-white rounded-xl border border-slate-200 p-4"
      >
        <h3 class="text-base font-semibold text-gray-900">Completion checklist</h3>
        <p class="text-xs text-slate-500 mb-3">
          Optional. Recorded against the job for later reference; never blocks invoicing.
        </p>

        <div class="space-y-2">
          <label
            v-for="item in checklistItems"
            :key="item.key"
            class="flex items-start gap-2 text-sm cursor-pointer"
          >
            <input
              v-model="checklist[item.key]"
              type="checkbox"
              :data-automation-id="`JobFinishTab-checklist-${item.key}`"
              class="mt-0.5 h-4 w-4 rounded border-slate-300"
              :disabled="savingChecklistKey !== null"
              @change="onChecklistToggle(item.key)"
            />
            <span class="text-slate-800">{{ item.label }}</span>
          </label>
        </div>

        <p
          v-if="props.pricingMethodology === 'time_materials'"
          data-automation-id="JobFinishTab-tm-urgency"
          class="mt-3 text-sm text-slate-600"
        >
          This is a Time &amp; Materials job, so the time and materials on it are what the customer
          pays. Get them right before invoicing.
        </p>

        <p class="mt-3 text-xs text-slate-500">Who ticked what is in the job history.</p>
      </section>

      <!-- COMPACT COST ANALYSIS -->
      <section class="bg-white rounded-xl border border-slate-200 p-4 space-y-4">
        <div>
          <h3 class="text-base font-semibold text-gray-900">Cost analysis</h3>
          <p class="text-xs text-slate-500">
            <span v-if="props.pricingMethodology === 'time_materials'">
              Estimate against actual for this Time &amp; Materials job
            </span>
            <span v-else-if="!showQuoteColumn"> Estimate against actual (no quote available) </span>
            <span v-else> Estimate, quote and actual with performance indicators </span>
          </p>
        </div>

        <!-- KAN-222 labour hours -->
        <div
          data-automation-id="JobFinishTab-labour-hours"
          class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm"
        >
          <div class="rounded-lg border border-slate-200 p-3">
            <div class="text-[11px] uppercase tracking-wide text-slate-500">Labour budget</div>
            <div
              data-automation-id="JobFinishTab-labour-budget"
              class="text-lg font-semibold tabular-nums text-slate-900"
            >
              {{ formatNumber(labourBudgetHours) }}
            </div>
          </div>
          <div class="rounded-lg border border-slate-200 p-3">
            <div class="text-[11px] uppercase tracking-wide text-slate-500">Hours used</div>
            <div
              data-automation-id="JobFinishTab-labour-used"
              class="text-lg font-semibold tabular-nums text-slate-900"
            >
              {{ formatNumber(actual.hours) }}
            </div>
          </div>
          <div
            class="rounded-lg border p-3"
            :class="labourOverrunHours > 0 ? 'border-red-200 bg-red-50' : 'border-slate-200'"
          >
            <div class="text-[11px] uppercase tracking-wide text-slate-500">
              {{ labourOverrunHours > 0 ? 'Overrun' : 'Hours remaining' }}
            </div>
            <div
              data-automation-id="JobFinishTab-labour-remaining"
              class="text-lg font-semibold tabular-nums"
              :class="labourOverrunHours > 0 ? 'text-red-700' : 'text-slate-900'"
            >
              {{ formatNumber(labourOverrunHours > 0 ? labourOverrunHours : labourRemainingHours) }}
            </div>
          </div>
        </div>

        <div class="overflow-x-auto">
          <table class="min-w-full bg-white rounded-lg border border-gray-200 text-sm">
            <thead>
              <tr class="bg-gray-50">
                <th class="py-2 px-4 text-left font-semibold text-gray-700">Metric</th>
                <th class="py-2 px-4 text-center font-semibold text-blue-700">Estimate</th>
                <th
                  v-if="showQuoteColumn"
                  class="py-2 px-4 text-center font-semibold text-green-700"
                >
                  Quote
                </th>
                <th class="py-2 px-4 text-center font-semibold text-orange-700">Actual</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td class="py-2 px-4 font-medium">Total Cost</td>
                <td class="py-2 px-4 text-center">{{ formatCurrency(estimate.cost) }}</td>
                <td v-if="showQuoteColumn" class="py-2 px-4 text-center">
                  {{ formatCurrency(quote.cost) }}
                </td>
                <td class="py-2 px-4 text-center">
                  <span :class="costClass">
                    {{ formatCurrency(actual.cost) }}
                    <span v-if="costDiff !== 0">
                      <component :is="costIcon" class="inline w-4 h-4 align-text-bottom ml-1" />
                      <span :class="costDiff > 0 ? 'text-red-600' : 'text-green-600'">
                        {{ formatPercent(costDiff) }}
                      </span>
                    </span>
                  </span>
                </td>
              </tr>
              <tr>
                <td class="py-2 px-4 font-medium">Total Revenue</td>
                <td class="py-2 px-4 text-center">{{ formatCurrency(estimate.rev) }}</td>
                <td v-if="showQuoteColumn" class="py-2 px-4 text-center">
                  {{ formatCurrency(quote.rev) }}
                </td>
                <td class="py-2 px-4 text-center">
                  <span :class="revenueClass">
                    {{ formatCurrency(actual.rev) }}
                    <span v-if="revenueDiff !== 0">
                      <component :is="revenueIcon" class="inline w-4 h-4 align-text-bottom ml-1" />
                      <span :class="revenueDiff > 0 ? 'text-green-600' : 'text-red-600'">
                        {{ formatPercent(revenueDiff) }}
                      </span>
                    </span>
                  </span>
                </td>
              </tr>
              <tr>
                <td class="py-2 px-4 font-medium">Profit Margin</td>
                <td class="py-2 px-4 text-center">{{ formatPercent(estimate.profitMargin) }}</td>
                <td v-if="showQuoteColumn" class="py-2 px-4 text-center">
                  {{ formatPercent(quote.profitMargin) }}
                </td>
                <td class="py-2 px-4 text-center">
                  <span :class="profitClass">
                    {{ formatPercent(actual.profitMargin) }}
                    <span v-if="profitDiff !== 0">
                      <component :is="profitIcon" class="inline w-4 h-4 align-text-bottom ml-1" />
                      <span :class="profitDiff > 0 ? 'text-green-600' : 'text-red-600'">
                        {{ formatPercent(profitDiff) }}
                      </span>
                    </span>
                  </span>
                </td>
              </tr>
              <tr>
                <td class="py-2 px-4 font-medium">Total Hours</td>
                <td class="py-2 px-4 text-center">{{ formatNumber(estimate.hours) }}</td>
                <td v-if="showQuoteColumn" class="py-2 px-4 text-center">
                  {{ formatNumber(quote.hours) }}
                </td>
                <td class="py-2 px-4 text-center">
                  <span :class="hoursClass">
                    {{ formatNumber(actual.hours) }}
                    <span v-if="hoursDiff !== 0">
                      <component :is="hoursIcon" class="inline w-4 h-4 align-text-bottom ml-1" />
                      <span :class="hoursDiff < 0 ? 'text-green-600' : 'text-red-600'">
                        {{ formatPercent(hoursDiff) }}
                      </span>
                    </span>
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="showQuoteColumn" class="flex flex-col md:flex-row gap-4">
          <div
            v-if="quotePerformance.status !== 'nodata'"
            class="flex-1 bg-white rounded-lg border border-gray-200 p-4 flex items-center gap-3"
          >
            <component
              :is="quoteAccuracyIcon"
              v-if="quoteAccuracyIcon"
              class="w-8 h-8"
              :class="quoteAccuracyClass"
            />
            <div>
              <div class="font-semibold text-gray-900">Quote Accuracy</div>
              <div class="text-lg font-bold" :class="quoteAccuracyClass">
                {{ formatPercent(quoteAccuracyDisplayValue) }}
              </div>
              <div class="text-xs text-gray-500">Deviation of actual cost from quoted cost</div>
            </div>
          </div>
          <div
            v-else
            class="flex-1 bg-gray-50 rounded-lg border border-gray-200 p-4 flex items-center gap-3"
          >
            <div class="w-8 h-8 bg-gray-300 rounded-full flex items-center justify-center">
              <span class="text-gray-500 text-sm">?</span>
            </div>
            <div>
              <div class="font-semibold text-gray-500">Quote Accuracy</div>
              <div class="text-sm text-gray-500">
                {{ !quote.cost ? 'No quote data available' : 'No actual data available' }}
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>

    <!-- Create Invoice Modal -->
    <Dialog :open="showInvoiceModal" @update:open="showInvoiceModal = $event">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Create Invoice</DialogTitle>
          <DialogDescription>
            {{ invoiceModalDescription }}
          </DialogDescription>
        </DialogHeader>
        <div class="space-y-4 py-4">
          <div class="rounded-lg bg-slate-50 p-3 text-sm space-y-1">
            <div class="flex justify-between">
              <span class="text-slate-600">{{ jobValueLabel }}</span>
              <span class="font-semibold tabular-nums">{{
                formatCurrency(summary.job_value_excl_gst)
              }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-slate-600">Already invoiced</span>
              <span class="font-semibold tabular-nums">{{
                formatCurrency(summary.valid_invoiced_excl_gst)
              }}</span>
            </div>
            <div class="flex justify-between border-t pt-1">
              <span class="text-slate-700 font-medium">Current amount to invoice</span>
              <span class="font-bold text-orange-600 tabular-nums">{{
                formatCurrency(summary.remaining_to_invoice_excl_gst)
              }}</span>
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
                  {{ formatCurrency(summary.remaining_to_invoice_excl_gst) }} excl GST
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

              <Button
                class="w-full h-auto py-4 px-4 flex flex-col items-start gap-1"
                variant="outline"
                data-automation-id="JobFinishTab-mode-invoice-amount"
                @click="selectInvoiceMode('invoice_amount')"
                :disabled="isCreatingInvoice"
              >
                <span class="font-semibold">Invoice $ amount</span>
                <span class="text-xs font-normal opacity-70">
                  {{ customAmountHint }}
                </span>
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
                  {{ formatCurrency(summary.remaining_to_invoice_excl_gst) }} excl GST
                </span>
              </Button>

              <Button
                class="w-full h-auto py-4 px-4 flex flex-col items-start gap-1"
                variant="outline"
                data-automation-id="JobFinishTab-mode-invoice-amount"
                @click="selectInvoiceMode('invoice_amount')"
                :disabled="isCreatingInvoice"
              >
                <span class="font-semibold">Invoice $ amount</span>
                <span class="text-xs font-normal opacity-70">
                  {{ customAmountHint }}
                </span>
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
            </template>
          </div>
        </div>
        <DialogFooter>
          <Button variant="ghost" @click="showInvoiceModal = false" :disabled="isCreatingInvoice"
            >Cancel</Button
          >
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { toast } from 'vue-sonner'
import debug from 'debug'
import { ArrowUp, ArrowDown, CheckCircle, AlertTriangle, XCircle } from 'lucide-vue-next'
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
import type { AxiosError } from 'axios'
import { z } from 'zod'

const log = debug('job:finish')

type FinishJobSummary = z.infer<typeof schemas.FinishJobSummary>
type JobCompletionChecklist = z.infer<typeof schemas.JobCompletionChecklist>
type ChecklistItemKey = keyof JobCompletionChecklist
type Invoice = z.infer<typeof schemas.Invoice>
type XeroInvoiceCreateRequest = z.infer<typeof schemas.XeroInvoiceCreateRequest>
type JobCostSetSummaryOutput = z.infer<typeof schemas.JobCostSetSummary>
type NormalizedCostSummary = {
  cost: number
  rev: number
  hours: number
  profitMargin: number
}

// Job statuses that mean the work itself is done. Purely a wording choice for
// invoice labels — invoicing stays available at every status.
const COMPLETED_STATUSES = ['recently_completed', 'archived']

const props = defineProps<{
  jobId: string
  pricingMethodology: string
  jobStatus?: string
  paid?: boolean
}>()

const emit = defineEmits<{
  'invoice-created': []
  'invoice-deleted': []
}>()

const loading = ref(true)
const { xeroConnected } = useXeroConnection()

const zeroSummary = (): FinishJobSummary => ({
  basis: props.pricingMethodology === 'fixed_price' ? 'quote' : 'actual_revenue',
  job_value_excl_gst: 0,
  valid_invoiced_excl_gst: 0,
  outstanding_invoiced_incl_gst: 0,
  remaining_to_invoice_excl_gst: 0,
  remaining_gst: 0,
  remaining_to_invoice_incl_gst: 0,
  total_to_pay_incl_gst: 0,
  over_invoiced_excl_gst: 0,
})

const summary = reactive<FinishJobSummary>(zeroSummary())
const checklist = reactive<JobCompletionChecklist>({
  foreman_signed_off: false,
  timesheets_collected: false,
  materials_checked: false,
  customer_called: false,
  released: false,
})

const invoices = ref<Array<Invoice>>([])
const isCreatingInvoice = ref(false)
const deletingInvoiceId = ref<string | null>(null)
const savingChecklistKey = ref<ChecklistItemKey | null>(null)

// --- Cost analysis state ---
const zeroCostSummary = (): NormalizedCostSummary => ({
  cost: 0,
  rev: 0,
  hours: 0,
  profitMargin: 0,
})
const estimate = reactive<NormalizedCostSummary>(zeroCostSummary())
const quote = reactive<NormalizedCostSummary>(zeroCostSummary())
const actual = reactive<NormalizedCostSummary>(zeroCostSummary())
const hasValidQuoteData = ref(false)

const ensureSummary = (s?: JobCostSetSummaryOutput | null): NormalizedCostSummary => ({
  cost: s?.cost ?? 0,
  rev: s?.rev ?? 0,
  hours: s?.hours ?? 0,
  profitMargin: s?.profitMargin ?? 0,
})

// --- Loading ---

async function loadFinishSummary() {
  const response = await api.job_jobs_finish_retrieve({ params: { job_id: props.jobId } })
  Object.assign(summary, response.summary)
  Object.assign(checklist, response.checklist)
}

async function loadInvoices() {
  const response = await api.job_jobs_invoices_retrieve({ params: { job_id: props.jobId } })
  invoices.value = response.invoices || []
}

async function loadCostSummary() {
  const response = await api.job_jobs_costs_summary_retrieve({ params: { job_id: props.jobId } })
  Object.assign(estimate, ensureSummary(response.estimate))
  Object.assign(quote, ensureSummary(response.quote))
  Object.assign(actual, ensureSummary(response.actual))
  hasValidQuoteData.value =
    !!response.quote && ((response.quote.cost ?? 0) > 0 || (response.quote.rev ?? 0) > 0)
}

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadFinishSummary(), loadInvoices(), loadCostSummary()])
  } catch (error) {
    log('Failed to load Finish Job data: %o', error)
    toast.error('Failed to load job financials')
  } finally {
    loading.value = false
  }
}

onMounted(loadAll)

// --- Balance presentation ---

const jobValueLabel = computed(() =>
  props.pricingMethodology === 'fixed_price'
    ? 'Quote total (excl GST)'
    : 'Job value to date (excl GST)',
)

const basisDescription = computed(() =>
  props.pricingMethodology === 'fixed_price'
    ? 'Calculated from the quote for this fixed-price job'
    : 'Calculated from actual revenue recorded on this Time & Materials job',
)

const canInvoiceFurther = computed(() => summary.remaining_to_invoice_excl_gst > 0)

const invoiceButtonText = computed(() => {
  if (!xeroConnected.value) return 'Login to Xero first'
  return 'Create Invoice'
})

// --- Stage-aware invoice wording (does not gate invoicing) ---

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

// --- Checklist ---

// The same questions on every job. Urgency differs between T&M and quoted work,
// but that is a note under the list, not a different list.
const checklistItems: Array<{ key: ChecklistItemKey; label: string }> = [
  { key: 'foreman_signed_off', label: 'Has the foreman signed off the job?' },
  { key: 'timesheets_collected', label: 'Have you collected the timesheet entries?' },
  { key: 'materials_checked', label: 'Have you checked the materials on the job?' },
  { key: 'customer_called', label: 'Have you called the customer?' },
  { key: 'released', label: 'Has the job been released?' },
]

// v-model has already applied the new value optimistically; this persists it and
// puts it back if the server refuses, so a tick never survives a failed save.
async function onChecklistToggle(key: ChecklistItemKey) {
  const checked = checklist[key]
  savingChecklistKey.value = key
  try {
    const response = await api.job_jobs_finish_partial_update(
      { [key]: checked },
      { params: { job_id: props.jobId } },
    )
    Object.assign(checklist, response.checklist)
  } catch (error) {
    log('Failed to save checklist item %s: %o', key, error)
    toast.error('Failed to save checklist')
    checklist[key] = !checked
  } finally {
    savingChecklistKey.value = null
  }
}

// --- Invoicing ---

const showInvoiceModal = ref(false)
const selectedInvoiceMode = ref<string | null>(null)
const invoicePercentInput = ref('')
const invoiceAmountInput = ref('')

const createInvoice = () => {
  selectedInvoiceMode.value = null
  invoicePercentInput.value = ''
  invoiceAmountInput.value = ''
  showInvoiceModal.value = true
}

function selectInvoiceMode(mode: string) {
  selectedInvoiceMode.value = mode
  invoicePercentInput.value = ''
  invoiceAmountInput.value = ''
}

async function executeCreateInvoice(mode: string) {
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
    const body = { mode } as XeroInvoiceCreateRequest
    if (percent !== undefined) body.percent = percent
    if (amount !== undefined) body.amount = amount

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
    emit('invoice-created')
    await refreshAfterInvoiceChange()
  } catch (err: unknown) {
    let msg = 'Unexpected error while trying to create invoice.'
    log('Error creating invoice: %o', err)
    if ((err as AxiosError).isAxiosError) {
      const axiosErr = err as AxiosError<{ message: string }>
      const errorData = axiosErr.response?.data
      if (typeof errorData === 'object' && errorData !== null && 'error' in errorData) {
        msg = String((errorData as { error: string }).error)
      }
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
    emit('invoice-deleted')
    await refreshAfterInvoiceChange()
  } catch (err) {
    log('Error deleting invoice: %o', err)
    toast.error('Failed to delete invoice.')
  } finally {
    deletingInvoiceId.value = null
  }
}

// The balance is only correct against the current invoice set, so it is
// re-read from the server rather than adjusted locally.
async function refreshAfterInvoiceChange() {
  try {
    await Promise.all([loadFinishSummary(), loadInvoices()])
  } catch (error) {
    log('Failed to refresh balance after invoice change: %o', error)
    toast.error('Invoice saved, but the balance could not be refreshed. Reload the job.')
  }
}

// --- KAN-222 labour hours ---

const labourBudgetHours = computed(() =>
  props.pricingMethodology === 'fixed_price' && hasValidQuoteData.value
    ? quote.hours
    : estimate.hours,
)
const labourRemainingHours = computed(() => Math.max(labourBudgetHours.value - actual.hours, 0))
const labourOverrunHours = computed(() => Math.max(actual.hours - labourBudgetHours.value, 0))

// --- Cost analysis comparisons ---

const showQuoteColumn = computed(() => {
  if (props.pricingMethodology === 'time_materials') return false
  return hasValidQuoteData.value || quote.cost > 0 || quote.rev > 0
})

function percentDiff(actualNum: number, refNum: number): number {
  if (!refNum) return 0
  return ((actualNum - refNum) / refNum) * 100
}

const useEstimateAsReference = computed(
  () => props.pricingMethodology === 'time_materials' || !showQuoteColumn.value,
)

const costRef = computed(() => (useEstimateAsReference.value ? estimate.cost : quote.cost))
const revRef = computed(() => (useEstimateAsReference.value ? estimate.rev : quote.rev))
const pmRef = computed(() =>
  useEstimateAsReference.value ? estimate.profitMargin : quote.profitMargin,
)
const hoursRef = computed(() => (useEstimateAsReference.value ? estimate.hours : quote.hours))

const costDiff = computed(() => percentDiff(actual.cost, costRef.value))
const revenueDiff = computed(() => percentDiff(actual.rev, revRef.value))
const profitDiff = computed(() => percentDiff(actual.profitMargin, pmRef.value))
const hoursDiff = computed(() => percentDiff(actual.hours, hoursRef.value))

const costClass = computed(() =>
  costDiff.value > 0 ? 'text-red-600 font-bold' : 'text-green-600 font-bold',
)
const costIcon = computed(() =>
  costDiff.value > 0 ? ArrowUp : costDiff.value < 0 ? ArrowDown : null,
)

const revenueClass = computed(() =>
  revenueDiff.value >= 0 ? 'text-green-600 font-bold' : 'text-red-600 font-bold',
)
const revenueIcon = computed(() =>
  revenueDiff.value > 0 ? ArrowUp : revenueDiff.value < 0 ? ArrowDown : null,
)

const profitClass = computed(() =>
  profitDiff.value >= 0 ? 'text-green-600 font-bold' : 'text-red-600 font-bold',
)
const profitIcon = computed(() =>
  profitDiff.value > 0 ? ArrowUp : profitDiff.value < 0 ? ArrowDown : null,
)

const hoursClass = computed(() =>
  hoursDiff.value <= 0 ? 'text-green-600 font-bold' : 'text-red-600 font-bold',
)
const hoursIcon = computed(() =>
  hoursDiff.value < 0 ? ArrowDown : hoursDiff.value > 0 ? ArrowUp : null,
)

const quotePerformance = computed(() => {
  if (!showQuoteColumn.value || !hasValidQuoteData.value || quote.cost === 0) {
    return { status: 'nodata' as const, deviation: 0 }
  }
  const deviation = Math.abs(percentDiff(actual.cost, quote.cost))
  if (deviation <= 20) return { status: 'good' as const, deviation }
  if (deviation <= 40) return { status: 'amber' as const, deviation }
  return { status: 'red' as const, deviation }
})

const quoteAccuracyIcon = computed(() => {
  switch (quotePerformance.value.status) {
    case 'good':
      return CheckCircle
    case 'amber':
      return AlertTriangle
    case 'red':
      return XCircle
    default:
      return null
  }
})

const quoteAccuracyClass = computed(() => {
  switch (quotePerformance.value.status) {
    case 'good':
      return 'text-green-600'
    case 'amber':
      return 'text-yellow-600'
    case 'red':
      return 'text-red-600'
    default:
      return 'text-gray-500'
  }
})

const quoteAccuracyDisplayValue = computed(() => {
  if (quotePerformance.value.status === 'nodata') return 0
  return percentDiff(actual.cost, quote.cost)
})

function formatPercent(value: number): string {
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`
}
function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value)
}
</script>

<style scoped>
table {
  border-collapse: separate;
  border-spacing: 0;
}
th,
td {
  border-bottom: 1px solid #e5e7eb;
}
th:last-child,
td:last-child {
  border-right: none;
}
</style>
