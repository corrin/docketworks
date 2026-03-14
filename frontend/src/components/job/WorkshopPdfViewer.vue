<template>
  <div class="h-full">
    <PDF v-if="pdfData" :src="pdfData" class="w-full h-full" />
    <div v-else-if="!hasError" class="flex items-center justify-center h-full">
      <div class="flex items-center gap-2">
        <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
        Workshop PDF is still loading, please wait
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
import { debugLog } from '@/utils/debug'

import { ref, onMounted } from 'vue'
import PDF from 'pdf-vue3'
import { jobService } from '@/services/job.service'

const props = defineProps<{ jobId: string }>()
const pdfData = ref<Uint8Array | null>(null)
const hasError = ref(false)

async function loadPdf() {
  hasError.value = false
  try {
    const blob = await jobService.getWorkshopPdf(props.jobId)
    const buffer = await blob.arrayBuffer()
    pdfData.value = new Uint8Array(buffer)
  } catch (err) {
    hasError.value = true
    debugLog('Error loading PDF:', err)
  }
}

function retryLoad() {
  loadPdf()
}

onMounted(() => {
  loadPdf()
})
</script>
