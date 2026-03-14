<script setup lang="ts">
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '../../components/ui/select'
import { Input } from '../../components/ui/input'
import { Badge } from '../../components/ui/badge'
import { useStockStore, type StockItem } from '../../stores/stockStore'
import { useCompanyDefaultsStore } from '../../stores/companyDefaults'
import { onMounted, computed, ref } from 'vue'
import { formatCurrency } from '@/utils/string-formatting'

type LabourItem = {
  id: '__labour__'
  description: string
  item_code: string
  unit_cost: number
  unit_rev: number
  unit_revenue: number
  quantity: null
}

type DisplayItem = StockItem | LabourItem

const props = withDefaults(
  defineProps<{
    modelValue: string | null
    disabled?: boolean
    showQuantity?: boolean
    lineKind?: string
    tabKind?: string
  }>(),
  {
    disabled: false,
    showQuantity: true,
    lineKind: undefined,
    tabKind: undefined,
  },
)

const emit = defineEmits<{
  'update:modelValue': [string | null]
  'update:description': [string]
  'update:unit_cost': [number | null]
  'update:kind': [string | null]
}>()

const store = useStockStore()
const companyDefaultsStore = useCompanyDefaultsStore()
const searchTerm = ref('')

// Mocked Labour item for time entries
const mockedLabourItem = computed<LabourItem>(() => ({
  id: '__labour__',
  description: 'Labour',
  item_code: 'LABOUR',
  unit_cost: companyDefaultsStore.companyDefaults?.wage_rate ?? 0,
  unit_rev: companyDefaultsStore.companyDefaults?.charge_out_rate ?? 0,
  unit_revenue: companyDefaultsStore.companyDefaults?.charge_out_rate ?? 0,
  quantity: null,
}))

onMounted(async () => {
  // Avoid triggering redundant fetches when many ItemSelects mount at once
  if (store.items.length === 0 && !store.loading) {
    await store.fetchStock()
  }
})

const filteredItems = computed<DisplayItem[]>(() => {
  const stockItems = store.items
  // Only show labour items in job-related contexts (estimate, quote, actual tabs)
  // Don't show labour in purchasing contexts
  const labourItem =
    props.tabKind === 'estimate' || props.tabKind === 'quote' ? [mockedLabourItem.value] : []

  // Include LABOUR only for job contexts, put it first
  const allItems = [...labourItem, ...stockItems]

  if (!searchTerm.value) return allItems
  const term = searchTerm.value.toLowerCase()
  return allItems.filter((item) => {
    const searchableFields = [item.description, item.item_code].filter(Boolean) // Remove null/undefined values

    return searchableFields.some((field) => field?.toLowerCase().includes(term))
  })
})

const displayPrice = (item: DisplayItem) => {
  return formatCurrency(item.unit_revenue ?? 0)
}
</script>

<template>
  <Select
    :model-value="props.modelValue"
    :disabled="props.disabled"
    class="!w-full min-w-64"
    @update:model-value="
      (val) => {
        emit('update:modelValue', val as string | null)

        if (val === '__labour__') {
          emit('update:description', 'Labour')
          emit('update:unit_cost', companyDefaultsStore.companyDefaults?.wage_rate ?? 0)
          emit('update:kind', 'time')
        } else {
          const found = store.items.find((i: StockItem) => i.id == val)

          if (found) {
            emit('update:description', found.description || '')
            emit('update:unit_cost', found.unit_cost || null)
            emit('update:kind', 'material')
          } else {
            emit('update:description', '')
            emit('update:unit_cost', null)
            emit('update:kind', null)
          }
        }
      }
    "
  >
    <SelectTrigger class="h-10 item-select-trigger" data-automation-id="ItemSelect-trigger">
      <SelectValue :placeholder="'Select Item'" />
    </SelectTrigger>

    <SelectContent class="max-h-80 w-[550px]">
      <!-- Search input -->
      <div class="p-3 border-b bg-muted/50">
        <Input
          v-model="searchTerm"
          placeholder="Search items by description, code, or type..."
          class="h-9 text-sm"
          @click.stop
          @keydown.stop
        />
      </div>

      <!-- Items list -->
      <div v-if="filteredItems.length === 0" class="p-4 text-sm text-muted-foreground text-center">
        {{ searchTerm ? 'No items found matching your search' : 'No stock items available' }}
      </div>

      <div v-else class="max-h-64 w-full overflow-y-auto">
        <SelectItem
          v-for="i in filteredItems"
          :key="i.id || 'unknown'"
          :value="i.id || ''"
          class="cursor-pointer p-4 border-b border-border last:border-b-0 hover:bg-accent/50 focus:bg-accent/50 bg-background w-full"
          :data-automation-id="`ItemSelect-option-${i.id === '__labour__' ? 'labour' : i.item_code || i.id}`"
        >
          <div class="flex w-full items-start justify-between gap-6 !min-w-[500px]">
            <div class="flex-1 min-w-0">
              <div class="font-medium text-sm leading-tight truncate">
                {{ i.description || 'Unnamed Item' }}
              </div>
              <div v-if="i.item_code" class="text-xs text-muted-foreground mt-1 truncate">
                Code: {{ i.item_code }}
              </div>
            </div>

            <div class="flex flex-col items-end gap-1 shrink-0">
              <Badge
                v-if="i.unit_revenue || i.unit_revenue === 0"
                variant="secondary"
                class="text-xs font-semibold"
              >
                {{ displayPrice(i) }}
              </Badge>
              <Badge v-else variant="secondary" class="text-xs"> No price </Badge>

              <div class="text-xs text-muted-foreground">
                {{ i.id === '__labour__' ? 'per hour' : '' }}
              </div>
            </div>
          </div>
        </SelectItem>
      </div>
    </SelectContent>
  </Select>
</template>
