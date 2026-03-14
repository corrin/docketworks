<template>
  <div class="quote-cost-lines-grid h-full flex flex-col">
    <div v-if="isLoading" class="flex-1 flex items-center justify-center">
      <div class="flex items-center space-x-2 text-gray-500">
        <svg class="animate-spin h-5 w-5" fill="none" viewBox="0 0 24 24">
          <circle
            class="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            stroke-width="4"
          ></circle>
          <path
            class="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          ></path>
        </svg>
        <span>Loading cost lines...</span>
      </div>
    </div>

    <div
      v-else-if="!costLines || costLines.length === 0"
      class="flex-1 flex items-center justify-center"
    >
      <div class="text-center py-8">
        <svg
          class="w-12 h-12 mx-auto mb-4 text-gray-300"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            stroke-linecap="round"
            stroke-linejoin="round"
            stroke-width="2"
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
        <p class="text-gray-500">No cost lines available</p>
      </div>
    </div>

    <div v-else class="flex-1 overflow-hidden">
      <div class="h-full overflow-auto">
        <table class="min-w-full divide-y divide-gray-200">
          <thead class="bg-gray-50 sticky top-0">
            <tr>
              <th
                class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
              >
                Type
              </th>
              <th
                class="px-4 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider"
              >
                Description
              </th>
              <th
                class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
              >
                Quantity
              </th>
              <th
                class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
              >
                Unit Cost
              </th>
              <th
                class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
              >
                Unit Revenue
              </th>
              <th
                class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
              >
                Total Cost
              </th>
              <th
                class="px-4 py-3 text-right text-xs font-medium text-gray-500 uppercase tracking-wider"
              >
                Total Revenue
              </th>
              <th
                class="px-4 py-3 text-center text-xs font-medium text-gray-500 uppercase tracking-wider"
              >
                Date
              </th>
            </tr>
          </thead>
          <tbody class="bg-white divide-y divide-gray-200">
            <tr
              v-for="(line, index) in costLines"
              :key="line.id || index"
              :class="['hover:bg-gray-50', line.kind === 'time' ? 'bg-blue-50' : 'bg-white']"
            >
              <td class="px-4 py-3 text-sm">
                <span
                  :class="[
                    'inline-flex px-2 py-1 text-xs font-semibold rounded-full',
                    line.kind === 'time'
                      ? 'bg-blue-100 text-blue-800'
                      : 'bg-green-100 text-green-800',
                  ]"
                >
                  {{ line.kind === 'time' ? 'Labour' : 'Material' }}
                </span>
              </td>
              <td class="px-4 py-3 text-sm text-gray-900">
                {{ line.desc }}
              </td>
              <td class="px-4 py-3 text-sm text-gray-900 text-right">
                {{ formatNumber(line.quantity || 0) }}
                <span v-if="line.kind === 'time'" class="text-xs text-gray-500 ml-1">hrs</span>
              </td>
              <td class="px-4 py-3 text-sm text-gray-900 text-right">
                {{ formatCurrency(line.unit_cost || 0) }}
              </td>
              <td class="px-4 py-3 text-sm text-gray-900 text-right">
                {{ formatCurrency(line.unit_rev || 0) }}
              </td>
              <td class="px-4 py-3 text-sm text-gray-900 text-right font-medium">
                {{ formatCurrency((line.quantity || 0) * (line.unit_cost || 0)) }}
              </td>
              <td class="px-4 py-3 text-sm text-gray-900 text-right font-medium">
                {{ formatCurrency((line.quantity || 0) * (line.unit_rev || 0)) }}
              </td>
              <td class="px-4 py-3 text-xs text-gray-500 text-center">
                <span
                  v-if="line.accounting_date"
                  :title="getFullDateTime(line.accounting_date)"
                  class="hover:text-gray-700"
                  style="cursor: pointer"
                >
                  {{ formatModifiedDate(line.accounting_date) }}
                </span>
                <span v-else class="text-gray-400">-</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { schemas } from '../../api/generated/api'
import { z } from 'zod'
import { formatCurrency } from '@/utils/string-formatting'

// Extend CostLine type to include timestamp fields (to be added to backend schema)
type CostLine = z.infer<typeof schemas.CostLine> & {
  created_at?: string
  updated_at?: string
}

withDefaults(
  defineProps<{
    costLines: CostLine[]
    isLoading?: boolean
  }>(),
  {
    isLoading: false,
  },
)

function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(value)
}

function getFullDateTime(dateString: string): string {
  if (!dateString) return ''
  return new Date(dateString).toLocaleString('en-NZ', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function formatModifiedDate(dateString: string): string {
  if (!dateString) return ''
  const date = new Date(dateString)
  const day = date.getDate().toString().padStart(2, '0')
  const month = date.toLocaleDateString('en-NZ', { month: 'short' }).toUpperCase()
  const year = date.getFullYear().toString().slice(-2)
  return `${day}/${month}/${year}`
}
</script>

<style scoped></style>
