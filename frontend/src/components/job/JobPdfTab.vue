<template>
  <div class="p-4 sm:p-6 lg:p-8 bg-gray-50/50 overflow-auto">
    <div class="max-w-7xl mx-auto">
      <!-- Header Section -->
      <div class="flex-shrink-0 mb-6">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-xl font-semibold text-gray-900 mb-2">
              Job #{{ jobNumber }} Print Sheet
            </h2>
            <p class="text-sm text-gray-600">Preview and print the job sheet PDF.</p>
          </div>

          <!-- Toolbar -->
          <div class="flex items-center space-x-3">
            <Button
              v-if="pdfBlob"
              variant="outline"
              size="sm"
              :disabled="isLoading"
              @click="maximizePdf"
            >
              <Maximize class="w-4 h-4 mr-2" />
              Maximize
            </Button>

            <Button
              v-if="pdfBlob"
              variant="outline"
              size="sm"
              :disabled="isLoading"
              @click="downloadPdf"
            >
              <Download class="w-4 h-4 mr-2" />
              Download
            </Button>

            <Button v-if="pdfBlob" size="sm" :disabled="isLoading" @click="printPdf">
              <Printer class="w-4 h-4 mr-2" />
              Print
            </Button>

            <Button
              v-if="pdfBlob"
              :disabled="isAttaching || isAttached || isLoading"
              size="sm"
              variant="secondary"
              @click="attachPdfToJob"
            >
              <template v-if="isAttaching">
                <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-current mr-2"></div>
                Attaching...
              </template>
              <template v-else-if="isAttached">
                <CheckCircle class="w-4 h-4 mr-2" />
                Attached
              </template>
              <template v-else>
                <Paperclip class="w-4 h-4 mr-2" />
                Attach to Job
              </template>
            </Button>
          </div>
        </div>
      </div>

      <!-- Error Display -->
      <Alert v-if="error" variant="destructive" class="mb-6">
        <AlertCircle class="h-4 w-4" />
        <AlertTitle>Error</AlertTitle>
        <AlertDescription>{{ error }}</AlertDescription>
      </Alert>

      <!-- PDF Viewer Section -->
      <Card class="min-h-[800px]">
        <CardContent class="p-0">
          <!-- Loading State -->
          <div v-if="isLoading" class="h-[800px] flex items-center justify-center">
            <div class="text-center">
              <div
                class="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500 mx-auto mb-4"
              ></div>
              <p class="text-gray-500">Generating PDF...</p>
            </div>
          </div>

          <!-- PDF Display -->
          <div v-else-if="pdfUrl" class="h-[800px]">
            <iframe :src="pdfUrl" class="w-full h-full border-0" title="Workshop PDF Preview" />
          </div>

          <!-- Empty State -->
          <div v-else class="h-[800px] flex items-center justify-center">
            <div class="text-center">
              <FileText class="w-16 h-16 text-gray-400 mx-auto mb-4" />
              <h3 class="text-lg font-medium text-gray-900 mb-2">No PDF Available</h3>
              <p class="text-gray-500 mb-4">Click the button below to generate the workshop PDF.</p>
              <Button @click="generatePdf" :disabled="isLoading">
                <FileText class="w-4 h-4 mr-2" />
                Generate PDF
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>

    <!-- Maximize PDF Modal -->
    <div v-if="isMaximized" class="fixed inset-0 z-50 bg-black/80 flex items-center justify-center">
      <div
        class="bg-white rounded-lg shadow-xl max-w-[95vw] max-h-[95vh] w-full h-full flex flex-col"
      >
        <!-- Modal Header -->
        <div class="flex items-center justify-between p-4 border-b bg-white rounded-t-lg">
          <h3 class="text-lg font-semibold">Job #{{ jobNumber }} Print Sheet - Full View</h3>
          <div class="flex items-center space-x-2">
            <Button variant="outline" size="sm" @click="downloadPdf">
              <Download class="w-4 h-4 mr-2" />
              Download
            </Button>
            <Button size="sm" @click="printPdf">
              <Printer class="w-4 h-4 mr-2" />
              Print
            </Button>
            <Button variant="ghost" size="sm" @click="isMaximized = false">
              <X class="w-4 h-4" />
            </Button>
          </div>
        </div>

        <!-- Modal Content -->
        <div class="flex-1 p-0" style="height: calc(95vh - 80px)">
          <iframe
            v-if="pdfUrl"
            :src="pdfUrl"
            class="w-full h-full border-0"
            title="Workshop PDF Preview - Full Screen"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import {
  Download,
  Printer,
  Paperclip,
  CheckCircle,
  AlertCircle,
  FileText,
  Maximize,
  X,
} from 'lucide-vue-next'
import { jobService } from '../../services/job.service'
import { toast } from 'vue-sonner'

// Simple inline components
const Alert = {
  template:
    '<div class="relative w-full rounded-lg border border-red-200 bg-red-50 p-4 text-red-800"><slot /></div>',
  props: { variant: String },
}
const AlertTitle = {
  template: '<h5 class="mb-1 font-medium leading-none tracking-tight"><slot /></h5>',
}
const AlertDescription = { template: '<div class="text-sm [&_p]:leading-relaxed"><slot /></div>' }

interface Props {
  jobId: string
  jobNumber: number
}

const props = defineProps<Props>()

// State
const isLoading = ref(false)
const error = ref<string | null>(null)
const pdfBlob = ref<Blob | null>(null)
const pdfUrl = ref<string | null>(null)
const isAttaching = ref(false)
const isAttached = ref(false)
const isMaximized = ref(false)

// Generate PDF from API
const generatePdf = async () => {
  if (!props.jobId) {
    error.value = 'Job ID is required to generate PDF'
    return
  }

  isLoading.value = true
  error.value = null

  try {
    const blob = await jobService.getWorkshopPdf(props.jobId)
    pdfBlob.value = blob

    // Create object URL for display
    if (pdfUrl.value) {
      URL.revokeObjectURL(pdfUrl.value)
    }
    pdfUrl.value = URL.createObjectURL(blob)

    toast.success('PDF generated successfully')
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : 'Failed to generate PDF'
    error.value = errorMessage
    toast.error('Failed to generate PDF', {
      description: errorMessage,
    })
    console.error('[JobPdfTab] Error generating PDF:', err)
  } finally {
    isLoading.value = false
  }
}

// Download PDF
const downloadPdf = () => {
  if (!pdfBlob.value) {
    toast.error('No PDF available to download')
    return
  }

  try {
    const url = URL.createObjectURL(pdfBlob.value)
    const link = document.createElement('a')
    link.href = url
    link.download = `workshop_job_${props.jobNumber}.pdf`
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)

    toast.success('PDF download started')
  } catch (err) {
    toast.error('Failed to download PDF')
    console.error('[JobPdfTab] Error downloading PDF:', err)
  }
}

// Print PDF
const printPdf = () => {
  if (!pdfUrl.value) {
    toast.error('No PDF available to print')
    return
  }

  try {
    const printWindow = window.open(pdfUrl.value, '_blank')
    if (printWindow) {
      printWindow.addEventListener('load', () => {
        printWindow.print()
      })
      toast.success('Print dialog opened')
    } else {
      toast.error('Failed to open print window. Please check popup blocker settings.')
    }
  } catch (err) {
    toast.error('Failed to print PDF')
    console.error('[JobPdfTab] Error printing PDF:', err)
  }
}

// Attach PDF to job as file
const attachPdfToJob = async () => {
  if (!pdfBlob.value || !props.jobId) {
    toast.error('PDF or job ID not available')
    return
  }

  isAttaching.value = true
  error.value = null

  try {
    // Create File object from blob
    const file = new File([pdfBlob.value], `workshop_job_${props.jobNumber}.pdf`, {
      type: 'application/pdf',
    })

    // Upload using job service
    await jobService.uploadJobFiles(props.jobId, [file])

    isAttached.value = true
    toast.success('PDF attached to job successfully')
  } catch (err) {
    const errorMessage = err instanceof Error ? err.message : 'Failed to attach PDF to job'
    error.value = errorMessage
    toast.error('Failed to attach PDF', {
      description: errorMessage,
    })
    console.error('[JobPdfTab] Error attaching PDF:', err)
  } finally {
    isAttaching.value = false
  }
}

// Maximize PDF in modal
const maximizePdf = () => {
  if (!pdfUrl.value) {
    toast.error('No PDF available to maximize')
    return
  }
  isMaximized.value = true
}

// Auto-generate PDF on mount
onMounted(() => {
  generatePdf()
})

// Cleanup object URLs
onUnmounted(() => {
  if (pdfUrl.value) {
    URL.revokeObjectURL(pdfUrl.value)
  }
})
</script>
