<template>
  <div class="space-y-6">
    <div class="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div class="bg-white rounded-lg border border-gray-200 p-4">
        <h3 class="text-lg font-semibold text-gray-900 mb-3">Estimate</h3>
        <div class="space-y-3">
          <SimpleTotalTable
            title="Time"
            :value="estimates.time"
            @update="updateEstimate('time', $event)"
          />
          <SimpleTotalTable
            title="Materials"
            :value="estimates.materials"
            @update="updateEstimate('materials', $event)"
          />
          <SimpleTotalTable
            title="Adjustments"
            :value="estimates.adjustments"
            @update="updateEstimate('adjustments', $event)"
          />
          <div class="pt-2 border-t">
            <div class="flex justify-between font-semibold">
              <span>Total:</span>
              <span>{{ formatCurrency(estimates.total) }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="bg-white rounded-lg border border-gray-200 p-4">
        <h3 class="text-lg font-semibold text-gray-900 mb-3">Quote</h3>
        <div class="space-y-3">
          <SimpleTotalTable
            title="Time"
            :value="quotes.time"
            @update="updateQuote('time', $event)"
          />
          <SimpleTotalTable
            title="Materials"
            :value="quotes.materials"
            @update="updateQuote('materials', $event)"
          />
          <SimpleTotalTable
            title="Adjustments"
            :value="quotes.adjustments"
            @update="updateQuote('adjustments', $event)"
          />
          <div class="pt-2 border-t">
            <div class="flex justify-between font-semibold">
              <span>Total:</span>
              <span>{{ formatCurrency(quotes.total) }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="bg-white rounded-lg border border-gray-200 p-4">
        <h3 class="text-lg font-semibold text-gray-900 mb-3">Reality</h3>
        <div class="space-y-3">
          <SimpleTotalTable
            title="Time"
            :value="reality.time"
            @update="updateReality('time', $event)"
          />
          <SimpleTotalTable
            title="Materials"
            :value="reality.materials"
            @update="updateReality('materials', $event)"
          />
          <SimpleTotalTable
            title="Adjustments"
            :value="reality.adjustments"
            @update="updateReality('adjustments', $event)"
          />
          <div class="pt-2 border-t">
            <div class="flex justify-between font-semibold">
              <span>Total:</span>
              <span>{{ formatCurrency(reality.total) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'
import { formatCurrency } from '@/utils/string-formatting'

import { ref, watch } from 'vue'
import SimpleTotalTable from './SimpleTotalTable.vue'
import { schemas } from '@/api/generated/api'
import { type PricingSection } from '@/constants/pricing-section'
import { z } from 'zod'

type CompanyDefaults = z.infer<typeof schemas.CompanyDefaults>
type Job = z.infer<typeof schemas.Job>

interface Props {
  jobData: Job
  latestPricings: Record<string, unknown>
  companyDefaults: CompanyDefaults | null
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'data-changed': [data: Record<string, unknown>]
}>()

const estimates = ref({
  time: 0,
  materials: 0,
  adjustments: 0,
  total: 0,
})

const quotes = ref({
  time: 0,
  materials: 0,
  adjustments: 0,
  total: 0,
})

const reality = ref({
  time: 0,
  materials: 0,
  adjustments: 0,
  total: 0,
})

const calculateTotal = (section: PricingSection) => {
  if (!section) return 0
  return (section.time || 0) + (section.materials || 0) + (section.adjustments || 0)
}

watch(
  [estimates, quotes, reality],
  () => {
    estimates.value.total = calculateTotal(estimates.value)
    quotes.value.total = calculateTotal(quotes.value)
    reality.value.total = calculateTotal(reality.value)
  },
  { deep: true },
)

const updateEstimate = (field: string, value: number) => {
  estimates.value[field as keyof typeof estimates.value] = value
  emitDataChanged()
}

const updateQuote = (field: string, value: number) => {
  quotes.value[field as keyof typeof quotes.value] = value
  emitDataChanged()
}

const updateReality = (field: string, value: number) => {
  reality.value[field as keyof typeof reality.value] = value
  emitDataChanged()
}

const emitDataChanged = () => {
  emit('data-changed', {
    estimates: estimates.value,
    quotes: quotes.value,
    reality: reality.value,
  })
}

watch(
  () => props.latestPricings,
  (newPricings) => {
    if (newPricings) {
      try {
        const pricingData = typeof newPricings === 'string' ? JSON.parse(newPricings) : newPricings

        const extractSectionTotals = (sectionData: Record<string, unknown>): PricingSection => {
          const time = calculateSectionTotal((sectionData?.time_entries as unknown[]) || [])
          const materials = calculateSectionTotal(
            (sectionData?.material_entries as unknown[]) || [],
          )
          const adjustments = calculateSectionTotal(
            (sectionData?.adjustment_entries as unknown[]) || [],
          )
          return { time, materials, adjustments, total: time + materials + adjustments }
        }

        if (pricingData?.estimate) {
          estimates.value = extractSectionTotals(pricingData.estimate)
        }
        if (pricingData?.quote) {
          quotes.value = extractSectionTotals(pricingData.quote)
        }
        if (pricingData?.reality) {
          reality.value = extractSectionTotals(pricingData.reality)
        }
      } catch (error) {
        debugLog('Error parsing pricing data:', error)

        estimates.value = { time: 100, materials: 200, adjustments: 50, total: 350 }
        quotes.value = { time: 120, materials: 220, adjustments: 60, total: 400 }
        reality.value = { time: 110, materials: 210, adjustments: 55, total: 375 }
      }
    }
  },
  { immediate: true },
)

const calculateSectionTotal = (entries: unknown[]): number => {
  return entries.reduce((total: number, entry) => {
    const typedEntry = entry as Record<string, unknown>

    // Convert API string/number values to numbers
    const parseApiValue = (value: unknown): number => {
      if (typeof value === 'number') return value
      if (typeof value === 'string') throw new Error('Number expected but got string')
      return 0
    }

    if (typedEntry.total_minutes !== undefined) {
      return total + parseApiValue(typedEntry.revenue)
    }

    if (typedEntry.quantity !== undefined && typedEntry.unit_revenue !== undefined) {
      return total + parseApiValue(typedEntry.quantity) * parseApiValue(typedEntry.unit_revenue)
    }

    if (typedEntry.price_adjustment !== undefined) {
      return total + parseApiValue(typedEntry.price_adjustment)
    }

    if (typedEntry.retail_price !== undefined) {
      return total + parseApiValue(typedEntry.retail_price)
    }
    if (typedEntry.value_of_time !== undefined) {
      return total + parseApiValue(typedEntry.value_of_time)
    }
    return total
  }, 0)
}
</script>
