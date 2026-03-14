<template>
  <div class="h-full">
    <PDF v-if="pdfData" :src="pdfData" class="w-full h-full" />
    <div v-else-if="!hasError" class="flex items-center justify-center h-full">
      <div class="flex items-center gap-2">
        <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
        Purchase Order PDF is still loading, please wait
      </div>
    </div>
    <div v-else class="flex items-center justify-center h-full text-red-600">
      <div class="text-center">
        <p class="mb-2">Failed to load PDF</p>
        <button @click="retryLoad" class="text-blue-600 hover:text-blue-800 underline">
          Try Again
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import PDF from 'pdf-vue3'
import { usePurchaseOrderStore } from '@/stores/purchaseOrderStore'
import { toast } from 'vue-sonner'

const props = defineProps<{
  purchaseOrderId: string
}>()

const pdfData = ref<Uint8Array | null>(null)
const hasError = ref(false)
const purchaseOrderStore = usePurchaseOrderStore()

async function loadPdf() {
  hasError.value = false
  try {
    const blob = await purchaseOrderStore.fetchPurchaseOrderPdf(props.purchaseOrderId)
    const buffer = await blob.arrayBuffer()
    pdfData.value = new Uint8Array(buffer)
  } catch (err) {
    hasError.value = true
    console.error('Error loading Purchase Order PDF:', err)
    const errorMessage = err instanceof Error ? err.message : 'Failed to load PDF'
    toast.error(`PDF loading failed: ${errorMessage}`)
  }
}

function retryLoad() {
  loadPdf()
}

onMounted(() => {
  loadPdf()
})
</script>
