<template>
  <AppLayout>
    <div class="p-6 max-w-3xl mx-auto space-y-8">
      <h1 class="text-xl font-bold" data-automation-id="PoCreateView-title">
        Create Purchase Order
      </h1>

      <PoSummaryCard
        :po="po"
        :is-create-mode="true"
        @update:reference="po.reference = $event"
        @update:expected_delivery="po.expected_delivery = $event"
        @update:status="po.status = $event"
        @update:supplier_id="po.supplier_id = $event"
        @update:supplier="po.supplier = $event"
        @save="save"
      />

      <div class="flex justify-end gap-2">
        <Button
          variant="secondary"
          @click="cancel"
          :disabled="saving"
          data-automation-id="PoCreateView-cancel"
          >Cancel</Button
        >
        <Button :disabled="saving" @click="save" data-automation-id="PoCreateView-save">
          <div v-if="saving" class="flex items-center gap-2">
            <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
            Creating PO...
          </div>
          <span v-else>Save</span>
        </Button>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import PoSummaryCard from '@/components/purchasing/PoSummaryCard.vue'
import { Button } from '@/components/ui/button'
import { useRouter } from 'vue-router'
import { usePurchaseOrderStore } from '@/stores/purchaseOrderStore'
import { toast } from 'vue-sonner'

import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type PurchaseOrderDetail = z.infer<typeof schemas.PurchaseOrderDetail>
type PurchaseOrderCreatePayload = z.infer<typeof schemas.PurchaseOrderCreateRequest>

const router = useRouter()
const store = usePurchaseOrderStore()
const saving = ref(false)

const po = ref<PurchaseOrderDetail>({
  po_number: '',
  supplier: '',
  supplier_has_xero_id: false,
  supplier_id: null,
  pickup_address_id: null,
  pickup_address: {} as PurchaseOrderDetail['pickup_address'],
  reference: '',
  expected_delivery: '',
  status: 'draft',
  id: '',
  order_date: '',
  lines: [],
  online_url: undefined,
  xero_id: undefined,
  created_by_id: null,
  created_by_name: '',
})

const save = async () => {
  saving.value = true
  try {
    const payload: PurchaseOrderCreatePayload = {
      supplier_id: po.value.supplier_id || null,
      reference: po.value.reference ?? '',
      order_date: po.value.order_date || null,
      expected_delivery: po.value.expected_delivery || null,
      lines: [],
    }
    const res = await store.createOrder(payload)
    toast.success('PO created')
    router.push(`/purchasing/po/${res.id}`)
  } catch (e: unknown) {
    const errorMessage = e instanceof Error ? e.message : 'Error creating PO'
    toast.error(errorMessage)
  } finally {
    saving.value = false
  }
}

const cancel = () => router.back()
</script>
