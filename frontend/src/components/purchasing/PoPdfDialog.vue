<template>
  <Dialog :open="props.open" @update:open="(val) => emit('update:open', val)">
    <DialogContent class="max-w-4xl w-full h-[80vh] p-5 m-5 flex flex-col">
      <DialogHeader>
        <DialogTitle>Purchase Order - PO #{{ poNumber }}</DialogTitle>
        <DialogDescription class="sr-only">
          Purchase Order PDF Viewer with options for download and print
        </DialogDescription>
        <DialogClose asChild> </DialogClose>
      </DialogHeader>
      <div class="flex-1 overflow-auto">
        <PoPdfViewer :purchase-order-id="purchaseOrderId" />
      </div>
      <footer class="border-t p-4 bg-gray-50 flex justify-end space-x-2">
        <Button v-if="blobUrl" variant="outline" size="icon" class="dark" asChild>
          <a :href="blobUrl" :download="`purchase_order_${props.poNumber}.pdf`" class="block p-2">
            <Download color="#fff" />
          </a>
        </Button>
        <Button v-if="blobUrl" @click="printPdf"> Print </Button>
      </footer>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogClose,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import PoPdfViewer from './PoPdfViewer.vue'
import { ref, watch } from 'vue'
import { usePurchaseOrderStore } from '@/stores/purchaseOrderStore'
import { Download } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

const props = defineProps<{
  purchaseOrderId: string
  poNumber: string | undefined
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
}>()

const blobUrl = ref<string>('')
const purchaseOrderStore = usePurchaseOrderStore()

watch(
  () => props.open,
  async (open) => {
    if (open) {
      try {
        toast.info('Generating PDF...', { id: 'po-pdf-loading' })
        const blob = await purchaseOrderStore.fetchPurchaseOrderPdf(props.purchaseOrderId)
        blobUrl.value = URL.createObjectURL(blob)
        toast.dismiss('po-pdf-loading')
        toast.success('PDF ready')
      } catch (err) {
        toast.dismiss('po-pdf-loading')
        console.error('Error generating Purchase Order PDF:', err)
        const errorMessage = err instanceof Error ? err.message : 'Failed to generate PDF'
        toast.error(`PDF generation failed: ${errorMessage}`)
        emit('update:open', false)
      }
    } else {
      // Clean up blob URL when dialog is closed to prevent memory leaks
      if (blobUrl.value) {
        URL.revokeObjectURL(blobUrl.value)
        blobUrl.value = ''
      }
    }
  },
)

function printPdf() {
  try {
    const win = window.open(blobUrl.value, '_blank')
    if (win) {
      win.print()
      toast.success('Print dialog opened')
    } else {
      toast.error('Failed to open print dialog. Please check if pop-ups are blocked.')
    }
  } catch (err) {
    console.error('Error printing PDF:', err)
    toast.error('Failed to print PDF')
  }
}
</script>
