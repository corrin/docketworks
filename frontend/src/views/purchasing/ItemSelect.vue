<script setup lang="ts">
import { Popover, PopoverContent, PopoverTrigger } from '../../components/ui/popover'
import { Input } from '../../components/ui/input'
import { Badge } from '../../components/ui/badge'
import { Button } from '../../components/ui/button'
import { useStockStore, type StockItem } from '../../stores/stockStore'
import { useCompanyDefaultsStore } from '../../stores/companyDefaults'
import { api } from '@/api/client'
import { useDebounceFn } from '@vueuse/core'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { formatCurrency } from '@/utils/string-formatting'

type LabourItem = {
  id: '__labour__'
  description: string
  item_code: string
  unit_cost: number
  unit_rev: number
  unit_revenue: number
  quantity: null
  times_used?: null
  metal_type?: string
  alloy?: string | null
  specifics?: string | null
}

type DisplayItem = StockItem | LabourItem

const props = withDefaults(
  defineProps<{
    modelValue: string | null
    open?: boolean
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
  'update:open': [boolean]
  'update:description': [string]
  'update:unit_cost': [number | null]
  'update:kind': [string | null]
  selectedItem: [DisplayItem | null]
}>()

const store = useStockStore()
const companyDefaultsStore = useCompanyDefaultsStore()
const searchTerm = ref('')
const serverResults = ref<StockItem[]>([])
const isSearching = ref(false)
const searchInput = ref<{ $el?: HTMLInputElement } | HTMLInputElement | null>(null)
const localOpen = ref(false)

// Mocked Labour item for time entries
const mockedLabourItem = computed<LabourItem>(() => ({
  id: '__labour__',
  description: 'Labour',
  item_code: 'LABOUR',
  unit_cost: companyDefaultsStore.companyDefaults?.wage_rate ?? 0,
  unit_rev: companyDefaultsStore.companyDefaults?.charge_out_rate ?? 0,
  unit_revenue: companyDefaultsStore.companyDefaults?.charge_out_rate ?? 0,
  quantity: null,
  times_used: null,
}))

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

  const stockItems = isQueryActive.value ? serverResults.value : []
  return [...labourItem, ...stockItems]
})

const popoverOpen = computed({
  get: () => props.open ?? localOpen.value,
  set: (nextOpen: boolean) => {
    localOpen.value = nextOpen
    handleOpenUpdate(nextOpen)
  },
})

const selectedDisplay = computed(() => {
  if (!props.modelValue) return 'Select Item'
  if (props.modelValue === '__labour__') return mockedLabourItem.value.item_code

  const found =
    serverResults.value.find((i: StockItem) => i.id === props.modelValue) ||
    store.items.find((i: StockItem) => i.id === props.modelValue)

  return found?.item_code || found?.description || 'Select Item'
})

const displayPrice = (item: DisplayItem) => {
  return formatCurrency(item.unit_revenue ?? 0)
}

function variantSignature(item: DisplayItem): string {
  if (item.id === '__labour__') return ''
  const stock = item as StockItem
  const metalType = stock.metal_type && stock.metal_type !== 'unspecified' ? stock.metal_type : null

  return [metalType, stock.alloy, stock.specifics]
    .map((part) => (part ?? '').toString().trim())
    .filter(Boolean)
    .join(' · ')
}

function usageLabel(item: DisplayItem): string {
  if (item.id === '__labour__') return ''
  return typeof item.times_used === 'number' && item.times_used > 0
    ? `Used ${item.times_used} times`
    : ''
}

function handleSelectedValue(val: string | null): void {
  emit('update:modelValue', val)
  popoverOpen.value = false

  if (val === '__labour__') {
    emit('selectedItem', mockedLabourItem.value)
    emit('update:description', 'Labour')
    emit('update:unit_cost', companyDefaultsStore.companyDefaults?.wage_rate ?? 0)
    emit('update:kind', 'time')
    return
  }

  const found =
    serverResults.value.find((i: StockItem) => i.id == val) ||
    store.items.find((i: StockItem) => i.id == val)

  emit('selectedItem', found ?? null)
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

async function focusSearchInput(): Promise<void> {
  await nextTick()
  window.setTimeout(() => {
    const input =
      searchInput.value instanceof HTMLInputElement ? searchInput.value : searchInput.value?.$el
    input?.focus()
  }, 0)
}

function handleOpenUpdate(nextOpen: boolean): void {
  emit('update:open', nextOpen)
  if (nextOpen) void focusSearchInput()
}

function handleSearchKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    popoverOpen.value = false
    return
  }
  event.stopPropagation()
}

watch(
  () => props.open,
  (nextOpen) => {
    if (nextOpen) void focusSearchInput()
  },
)

onMounted(() => {
  if (props.open) void focusSearchInput()
})
</script>

<template>
  <Popover v-model:open="popoverOpen">
    <PopoverTrigger as-child>
      <Button
        type="button"
        variant="outline"
        :disabled="disabled"
        class="h-10 item-select-trigger w-full min-w-64 justify-between font-normal"
        data-automation-id="ItemSelect-trigger"
      >
        <span class="truncate">{{ selectedDisplay }}</span>
      </Button>
    </PopoverTrigger>

    <PopoverContent class="max-h-80 w-[550px] overflow-y-auto p-0" align="start">
      <!-- Search input -->
      <div class="p-3 border-b bg-muted/50">
        <Input
          ref="searchInput"
          v-model="searchTerm"
          placeholder="Search items by description, code, or type..."
          class="h-9 text-sm"
          @click.stop
          @keydown="handleSearchKeydown"
        />
      </div>

      <!-- Items list -->
      <div v-if="filteredItems.length === 0" class="p-4 text-sm text-muted-foreground text-center">
        <span v-if="isSearching">Searching…</span>
        <span v-else-if="!isQueryActive"> Type at least 3 characters to search items </span>
        <span v-else>
          {{ searchTerm ? 'No items found matching your search' : 'No stock items available' }}
        </span>
      </div>

      <button
        v-for="i in filteredItems"
        :key="i.id || 'unknown'"
        type="button"
        class="cursor-pointer p-4 border-b border-border last:border-b-0 hover:bg-accent/50 focus:bg-accent/50 bg-background w-full text-left"
        :data-automation-id="`ItemSelect-option-${i.id === '__labour__' ? 'labour' : i.item_code || i.id}`"
        @click="handleSelectedValue(i.id || null)"
      >
        <div class="flex w-full items-start justify-between gap-6 !min-w-[500px]">
          <div class="flex-1 min-w-0">
            <div class="font-medium text-sm leading-tight whitespace-normal break-words">
              {{ i.description || 'Unnamed Item' }}
            </div>
            <div
              v-if="usageLabel(i) || variantSignature(i)"
              class="mt-1 flex flex-wrap gap-x-2 gap-y-1 text-xs text-muted-foreground"
            >
              <span v-if="usageLabel(i)" data-automation-id="ItemSelect-times-used">
                {{ usageLabel(i) }}
              </span>
              <span v-if="variantSignature(i)" data-automation-id="ItemSelect-variant-signature">
                {{ variantSignature(i) }}
              </span>
            </div>
            <div v-if="i.item_code" class="mt-1 text-xs text-muted-foreground truncate">
              <span data-automation-id="ItemSelect-code">
                {{ i.item_code }}
              </span>
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
      </button>
    </PopoverContent>
  </Popover>
</template>
