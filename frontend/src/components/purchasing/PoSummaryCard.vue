<script lang="ts" setup>
import { Card, CardHeader, CardContent, CardFooter } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { DatePicker } from '@/components/ui/date-picker'
import {
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from '@/components/ui/select'
import {
  Check,
  AlertCircle,
  UploadCloud,
  ExternalLink,
  Printer,
  Mail,
  CalendarIcon,
} from 'lucide-vue-next'
import ClientLookup from '@/components/ClientLookup.vue'
import PickupAddressSelector from '@/components/purchasing/PickupAddressSelector.vue'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'
import { reactive, watch } from 'vue' // ✅ 1. Import watch

type Status = z.infer<typeof schemas.PurchaseOrderDetailStatusEnum>
type PurchaseOrder = z.infer<typeof schemas.PurchaseOrderDetail>

const props = defineProps<{
  po: PurchaseOrder
  isCreateMode?: boolean
  showActions?: boolean
  syncEnabled?: boolean
  supplierReadonly?: boolean
}>()

const emit = defineEmits<{
  'update:supplier': [v: string]
  'update:supplier_id': [v: string]
  'update:pickup_address_id': [v: string | null]
  'update:reference': [v: string]
  'update:expected_delivery': [v: string]
  'update:status': [v: Status]
  save: []
  'sync-xero': []
  'view-xero': []
  print: []
  email: []
}>()

const supplierLookup = reactive({
  value: true, // indicates supplier mode vs client mode
})

// ✅ 2. Add autosave logic
let autosaveTimer: number | undefined = undefined

function scheduleSave() {
  // Clear any existing timer to reset the debounce period
  clearTimeout(autosaveTimer)

  // Set a new timer to emit the save event after 750ms of inactivity
  autosaveTimer = window.setTimeout(() => {
    emit('save')
  }, 750)
}

// Supplier changes are patched separately in the parent view to avoid firing saves mid-lookup
watch(
  () => [props.po.reference, props.po.expected_delivery, props.po.status],
  (newValues, oldValues) => {
    // Trigger autosave only on changes after the initial load, and not in create mode
    if (oldValues && !props.isCreateMode) {
      scheduleSave()
    }
  },
  { deep: true }, // 'deep' ensures we watch for changes inside the 'po' object
)

function onExpectedDeliveryUpdate(value: string) {
  emit('update:expected_delivery', value)
}

function onReferenceUpdate(value: string | number) {
  emit('update:reference', typeof value === 'number' ? String(value) : value)
}

function onStatusUpdate(value: Status) {
  emit('update:status', value)
}

function onSupplierSelected(client: { name?: string } | null) {
  emit('update:supplier', client?.name || '')
}

function onSupplierIdUpdate(id: string | null) {
  emit('update:supplier_id', id ?? '')
}

function onPickupAddressUpdate(addressId: string) {
  emit('update:pickup_address_id', addressId || null)
}

function formatDate(dateString: string | null | undefined): string {
  if (!dateString) return ''
  try {
    const date = new Date(dateString)
    return date.toLocaleDateString('en-NZ', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })
  } catch {
    return dateString
  }
}

const statusOptions: { value: Status; label: string }[] = [
  { value: 'draft', label: 'Draft' },
  { value: 'submitted', label: 'Submitted to Supplier' },
  { value: 'partially_received', label: 'Partially Received' },
  { value: 'fully_received', label: 'Fully Received' },
  { value: 'deleted', label: 'Deleted' },
]
</script>

<template>
  <Card class="max-w-[420px] w-full">
    <CardHeader v-if="!isCreateMode">
      <h2 class="font-semibold" data-automation-id="PoSummaryCard-po-number">
        PO #{{ po.po_number }}
      </h2>
    </CardHeader>

    <CardContent>
      <div class="flex flex-col gap-1">
        <template v-if="po.status === 'draft'">
          <ClientLookup
            :supplier-lookup="supplierLookup"
            id="supplier"
            :model-value="po.supplier"
            required
            placeholder="Search supplier…"
            @update:selected-client="onSupplierSelected"
            @update:selected-id="onSupplierIdUpdate"
            :label="'Supplier'"
            data-automation-id="PoSummaryCard-supplier-lookup"
          />
        </template>
        <template v-else>
          <Label for="supplier-readonly">Supplier</Label>
          <div class="flex items-center gap-2">
            <Input
              id="supplier-readonly"
              :model-value="po.supplier || ''"
              disabled
              class="flex-1 px-2 py-1 text-sm"
              placeholder="No supplier selected"
            />
            <span
              class="flex items-center px-1 py-0.5 rounded text-[11px] font-semibold"
              :class="
                po.supplier_has_xero_id
                  ? 'bg-green-100 text-green-800 border border-green-200'
                  : 'bg-red-100 text-red-800 border border-red-200'
              "
            >
              Xero
              <component :is="po.supplier_has_xero_id ? Check : AlertCircle" class="w-3 h-3 ml-1" />
            </span>
          </div>
        </template>
      </div>

      <!-- Pickup Address Selector - shown when supplier is selected -->
      <div v-if="po.supplier_id" class="flex flex-col gap-1 mt-4">
        <PickupAddressSelector
          id="pickup-address"
          label="Pickup Address"
          placeholder="Select pickup location"
          :optional="true"
          :supplier-id="po.supplier_id"
          :supplier-name="po.supplier"
          :initial-address-id="po.pickup_address_id || ''"
          @update:model-value="onPickupAddressUpdate"
        />
      </div>

      <div class="flex flex-col gap-1 mt-4">
        <Label for="reference">Reference</Label>
        <Input
          id="reference"
          :model-value="po.reference || ''"
          @update:model-value="onReferenceUpdate"
          class="w-full"
          data-automation-id="PoSummaryCard-reference"
        />
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mt-4">
        <div class="flex flex-col gap-2">
          <div class="flex flex-col gap-1">
            <label class="text-sm font-medium">Order Date</label>
            <Button variant="outline" class="justify-start font-normal w-full bg-gray-50" disabled>
              <CalendarIcon class="mr-2 h-4 w-4" />
              {{ formatDate(po.order_date) || 'Today' }}
            </Button>
          </div>
        </div>
        <div class="flex flex-col gap-2">
          <DatePicker
            label="Expected Delivery"
            :modelValue="po.expected_delivery || null"
            @update:modelValue="(value) => onExpectedDeliveryUpdate(value || '')"
          />
        </div>
      </div>

      <div class="flex flex-col gap-1 mt-4" v-if="!isCreateMode">
        <Label>Created By</Label>
        <Input
          :model-value="po.created_by_name || ''"
          disabled
          class="bg-gray-50"
          data-automation-id="PoSummaryCard-created-by"
        />
      </div>

      <div class="flex flex-col gap-2 mt-4" v-if="!isCreateMode">
        <div class="flex flex-col items-center gap-1">
          <Label for="status">Status</Label>
          <Select
            id="status"
            :modelValue="po.status || null"
            @update:modelValue="(value) => onStatusUpdate(value as Status)"
          >
            <SelectTrigger data-automation-id="PoSummaryCard-status-trigger">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem
                v-for="option in statusOptions"
                :key="option.value"
                :value="option.value"
                :data-automation-id="`PoSummaryCard-status-${option.value}`"
              >
                {{ option.label }}
              </SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
    </CardContent>

    <CardFooter v-if="!isCreateMode && showActions" class="flex flex-col gap-2">
      <div class="flex justify-center">
        <Button
          variant="default"
          :disabled="!syncEnabled"
          @click="$emit('sync-xero')"
          aria-label="Sync with Xero"
        >
          <UploadCloud class="mr-2 h-4 w-4" /> Sync with Xero
        </Button>
      </div>

      <div v-if="po.online_url" class="flex flex-wrap gap-2">
        <Button variant="outline" @click="$emit('view-xero')" aria-label="View in Xero">
          <ExternalLink class="mr-2 h-4 w-4" /> View in Xero
        </Button>
        <Button variant="outline" aria-label="Print" @click="$emit('print')">
          <Printer class="mr-2 h-4 w-4" /> Print
        </Button>
        <Button variant="outline" aria-label="E-mail" @click="$emit('email')">
          <Mail class="mr-2 h-4 w-4" /> E-mail
        </Button>
      </div>

      <div v-else class="flex flex-wrap gap-2">
        <Button variant="outline" aria-label="Print" @click="$emit('print')">
          <Printer class="mr-2 h-4 w-4" /> Print
        </Button>
        <Button variant="outline" aria-label="E-mail" @click="$emit('email')">
          <Mail class="mr-2 h-4 w-4" /> E-mail
        </Button>
      </div>
    </CardFooter>
  </Card>
</template>
