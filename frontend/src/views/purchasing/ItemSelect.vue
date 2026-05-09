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
import { api } from '@/api/client'
import { useDebounceFn } from '@vueuse/core'
import { onMounted, computed, ref, watch } from 'vue'
import { formatCurrency } from '@/utils/string-formatting'

type LabourItem = {
  id: '__labour__'
  description: string
  item_code: string
  unit_cost: number
  unit_rev: number
  unit_revenue: number
  quantity: null
  metal_type?: string
  alloy?: string | null
  specifics?: string | null
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
const serverResults = ref<StockItem[]>([])
const isSearching = ref(false)

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

const isQueryActive = computed(() => searchTerm.value.trim().length >= 3)

async function runSearch() {
  if (!isQueryActive.value) {
    serverResults.value = []
    return
  }
  isSearching.value = true
  try {
    const response = await api.purchasing_stock_search_retrieve({
      queries: {
        q: searchTerm.value.trim(),
        page: 1,
        page_size: 50,
      },
    })
    serverResults.value = response.results
  } catch (error) {
    console.error('ItemSelect stock search failed:', error)
    serverResults.value = []
  } finally {
    isSearching.value = false
  }
}

const debouncedSearch = useDebounceFn(runSearch, 300)

watch(searchTerm, () => {
  debouncedSearch()
})

const filteredItems = computed<DisplayItem[]>(() => {
  // Only show labour in job-related contexts (estimate, quote, actual tabs).
  const labourItem =
    props.tabKind === 'estimate' || props.tabKind === 'quote' ? [mockedLabourItem.value] : []

  const stockItems = isQueryActive.value ? serverResults.value : store.items
  return [...labourItem, ...stockItems]
})

const displayPrice = (item: DisplayItem) => {
  return formatCurrency(item.unit_revenue ?? 0)
}

function variantSignature(item: DisplayItem): string {
  if (item.id === '__labour__') return ''
  const stock = item as StockItem
  return [stock.metal_type, stock.alloy, stock.specifics]
    .map((part) => (part ?? '').toString().trim())
    .filter(Boolean)
    .join(' · ')
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
          const found =
            serverResults.find((i: StockItem) => i.id == val) ||
            store.items.find((i: StockItem) => i.id == val)

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
        <span v-if="isSearching">Searching…</span>
        <span v-else>
          {{ searchTerm ? 'No items found matching your search' : 'No stock items available' }}
        </span>
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
              <div class="font-medium text-sm leading-tight whitespace-normal break-words">
                {{ i.description || 'Unnamed Item' }}
              </div>
              <div
                v-if="variantSignature(i)"
                class="text-xs text-muted-foreground mt-1"
                data-automation-id="ItemSelect-variant-signature"
              >
                {{ variantSignature(i) }}
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
