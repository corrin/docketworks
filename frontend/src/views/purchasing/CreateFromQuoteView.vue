<template>
  <AppLayout>
    <div class="p-4 md:p-8 space-y-6">
      <div class="flex items-center gap-2">
        <ArrowLeft class="w-5 h-5 cursor-pointer" @click="goBack" />
        <h1 class="text-xl font-bold flex items-center gap-2">
          <FileSpreadsheet class="w-6 h-6 text-indigo-600" />
          Create Purchase Order from Quote
        </h1>
      </div>

      <div class="max-w-2xl mx-auto">
        <div class="bg-white rounded-lg border border-gray-200 shadow-sm p-4">
          <div class="space-y-6">
            <div class="text-center">
              <FileSpreadsheet class="w-16 h-8 mx-auto text-indigo-600 mb-4" />
              <h2 class="text-xl font-semibold mb-2">Upload Supplier Quote</h2>
              <p class="text-gray-600 mb-6">
                Upload a supplier quote file (preferably in PDF) and we'll automatically extract the
                data to create a purchase order.
              </p>
            </div>

            <form @submit.prevent="handleSubmit" class="space-y-6">
              <div class="space-y-2">
                <label for="quote-file" class="block text-sm font-medium text-gray-700">
                  Quote File *
                </label>
                <div
                  class="border-2 border-dashed border-gray-300 rounded-lg p-6 text-center hover:border-indigo-500 transition-colors"
                  :class="{ 'border-indigo-500 bg-indigo-50': dragActive }"
                  @dragover.prevent="dragActive = true"
                  @dragleave.prevent="dragActive = false"
                  @drop.prevent="handleDrop"
                  @click="fileInput?.click()"
                >
                  <input
                    ref="fileInput"
                    id="quote-file"
                    type="file"
                    accept=".pdf,.xlsx,.xls,.docx,.doc"
                    @change="handleFileSelect"
                    class="hidden"
                    required
                  />

                  <div v-if="selectedFile" class="flex items-center justify-center gap-2">
                    <FileCheck class="w-8 h-8 text-green-600" />
                    <div class="text-left">
                      <p class="font-medium text-gray-900">{{ selectedFile.name }}</p>
                      <p class="text-sm text-gray-500">
                        {{ formatFileSize(selectedFile.size) }} - Click to change
                      </p>
                    </div>
                  </div>

                  <div v-else class="space-y-2">
                    <Upload class="w-12 h-12 mx-auto text-gray-400" />
                    <p class="text-gray-600">
                      <span class="font-medium text-indigo-600 cursor-pointer">
                        Click to upload
                      </span>
                      or drag and drop
                    </p>
                    <p class="text-sm text-gray-500">PDF, Excel, or Word files up to 10MB</p>
                  </div>
                </div>
              </div>

              <div class="flex justify-end gap-3">
                <Button type="button" variant="outline" @click="goBack"> Cancel </Button>
                <Button
                  type="submit"
                  :disabled="!selectedFile || isUploading"
                  class="flex items-center gap-2"
                >
                  <Sparkles v-if="!isUploading" class="w-4 h-4" />
                  <Loader2 v-else class="w-4 h-4 animate-spin" />
                  {{
                    isUploading
                      ? 'Processing with AI (this may take up to 5 minutes)...'
                      : 'Extract & Create PO'
                  }}
                </Button>
              </div>
            </form>

            <div class="border-t pt-4">
              <h3 class="font-medium text-gray-900 mb-2">What happens next?</h3>
              <ul class="text-sm text-gray-600 space-y-1">
                <li class="flex items-center gap-2">
                  <CheckCircle class="w-4 h-4 text-green-500" />
                  AI will extract supplier details and line items
                </li>
                <li class="flex items-center gap-2">
                  <CheckCircle class="w-4 h-4 text-green-500" />
                  A draft purchase order will be created
                </li>
                <li class="flex items-center gap-2">
                  <CheckCircle class="w-4 h-4 text-green-500" />
                  You can review and edit before submitting
                </li>
              </ul>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import {
  ArrowLeft,
  FileSpreadsheet,
  Upload,
  FileCheck,
  Sparkles,
  CheckCircle,
  Loader2,
} from 'lucide-vue-next'
// TODO: Remove this axios import when supplier-quotes endpoint is added to generated API
// The /purchasing/api/supplier-quotes/extract/ endpoint is not yet available in Zodios
import api from '@/plugins/axios'

const router = useRouter()
const selectedFile = ref<File | null>(null)
const isUploading = ref(false)
const dragActive = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)

const goBack = () => {
  router.push('/purchasing/po')
}

const handleFileSelect = (event: Event) => {
  const target = event.target as HTMLInputElement
  if (target.files && target.files.length > 0) {
    selectedFile.value = target.files[0]
  }
}

const handleDrop = (event: DragEvent) => {
  dragActive.value = false
  if (event.dataTransfer?.files && event.dataTransfer.files.length > 0) {
    selectedFile.value = event.dataTransfer.files[0]
  }
}

const formatFileSize = (bytes: number): string => {
  if (bytes === 0) return '0 Bytes'
  const k = 1024
  const sizes = ['Bytes', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return (bytes / Math.pow(k, i)).toFixed(2) + ' ' + sizes[i]
}

const handleSubmit = async () => {
  if (!selectedFile.value) {
    toast.error('Please select a file to upload')
    return
  }

  // Validate file size (10MB max)
  const maxSize = 10 * 1024 * 1024 // 10MB
  if (selectedFile.value.size > maxSize) {
    toast.error('File size must be less than 10MB')
    return
  }

  // Validate file type
  const allowedTypes = [
    'application/pdf',
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    'application/vnd.ms-excel',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    'application/msword',
  ]

  if (!allowedTypes.includes(selectedFile.value.type)) {
    toast.error('Please upload a PDF, Excel, or Word document')
    return
  }

  isUploading.value = true

  try {
    const formData = new FormData()
    formData.append('quote_file', selectedFile.value)

    // Call the extract endpoint with extended timeout for AI processing
    const response = await api.post('/purchasing/api/supplier-quotes/extract/', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      timeout: 300000, // 5 minutes timeout for AI processing
    })

    // Handle JSON response
    if (response.data?.success) {
      const { purchase_order_id, message } = response.data

      toast.success(message || 'Quote processed successfully!')

      // Redirect to the PO detail page
      setTimeout(() => {
        router.push(`/purchasing/po/${purchase_order_id}`)
      }, 1500)
    } else {
      throw new Error(response.data?.error || 'Unknown error occurred')
    }
  } catch (error: unknown) {
    console.error('Error uploading quote:', error)

    let errorMessage = 'Failed to process the quote. Please try again.'

    // Type-safe error handling
    if (error instanceof Error) {
      errorMessage = error.message
    } else if (typeof error === 'object' && error !== null && 'response' in error) {
      const responseError = error as { response?: { data?: { error?: string } } }
      if (responseError.response?.data?.error) {
        errorMessage = responseError.response.data.error
      }
    }

    toast.error(errorMessage)
  } finally {
    isUploading.value = false
  }
}
</script>
