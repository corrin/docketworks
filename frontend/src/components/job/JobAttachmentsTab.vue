<template>
  <div class="p-4 sm:p-6 lg:p-8 h-full overflow-y-auto bg-gray-50/50">
    <div class="max-w-7xl mx-auto">
      <!-- Grid Layout: 2 columns -->
      <div class="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <!-- Left Column: Job Attachments & Upload -->
        <div class="flex flex-col h-full">
          <div class="mb-6 flex items-center justify-between">
            <div>
              <h2 class="text-xl font-semibold text-gray-900 mb-2">Job Attachments</h2>
              <p class="text-sm text-gray-600">
                Manage files and attachments for Job #{{ jobNumber }}.
              </p>
            </div>
            <button
              @click="openCameraModal"
              :disabled="!jobNumber || isUploading"
              class="inline-flex items-center px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-all duration-200"
            >
              <Camera class="w-4 h-4 mr-2" />
              Capture Photo
            </button>
          </div>

          <!-- File Upload Drop Zone -->
          <div
            @drop="handleDrop"
            @dragover.prevent="handleDragOver"
            @dragenter.prevent="handleDragEnter"
            @dragleave="handleDragLeave"
            data-automation-id="JobAttachmentsTab-dropzone"
            :class="[
              'border-2 border-dashed rounded-lg p-8 text-center transition-all duration-300 cursor-pointer',
              isDragOver
                ? 'border-blue-500 bg-blue-50 scale-[1.02] shadow-lg'
                : 'border-gray-300 hover:border-gray-400 hover:bg-gray-50',
              isUploading && 'pointer-events-none opacity-50',
            ]"
            @click="triggerFileInput"
          >
            <div class="flex flex-col items-center">
              <div :class="['transition-transform duration-300', isDragOver ? 'scale-110' : '']">
                <Upload class="mx-auto h-12 w-12 text-gray-400" />
              </div>
              <div class="mt-4">
                <p class="text-base text-gray-600">
                  <span class="font-semibold text-blue-600 hover:text-blue-500">
                    Click to upload
                  </span>
                  or drag and drop
                </p>
                <p class="text-sm text-gray-500 mt-1">PNG, JPG, PDF up to 10MB</p>
              </div>
            </div>
          </div>

          <input
            ref="fileInput"
            type="file"
            multiple
            data-automation-id="JobAttachmentsTab-file-input"
            @change="handleFileChange"
            accept="image/*,.pdf,.doc,.docx,.txt"
            class="hidden"
          />

          <!-- Upload Progress -->
          <div
            v-if="uploadProgress > 0 && uploadProgress < 100"
            class="bg-white rounded-lg border border-gray-200 p-6 shadow-sm mt-6"
          >
            <div class="flex items-center justify-between mb-2">
              <span class="text-sm font-medium text-gray-700">Uploading files...</span>
              <span class="text-sm text-gray-500">{{ uploadProgress.toFixed(2) }}%</span>
            </div>
            <div class="w-full bg-gray-200 rounded-full h-2">
              <div
                class="bg-blue-600 h-2 rounded-full transition-all duration-300 ease-out"
                :style="{ width: `${uploadProgress}%` }"
              ></div>
            </div>
          </div>
        </div>

        <!-- Right Column: Attached Files -->
        <div class="flex flex-col h-full">
          <div class="bg-white rounded-lg border border-gray-200 shadow-sm h-full flex flex-col">
            <div class="p-6 flex-1 flex flex-col">
              <h3 class="text-lg font-medium text-gray-900 mb-4">Attached Files</h3>

              <div v-if="isLoading" class="flex items-center justify-center py-12 flex-1">
                <div class="flex flex-col items-center gap-3">
                  <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
                  <p class="text-sm text-gray-500">Loading attachments...</p>
                </div>
              </div>

              <div v-else-if="files.length === 0" class="text-center py-12 flex-1">
                <FileText class="mx-auto h-12 w-12 text-gray-400 mb-4" />
                <h3 class="text-sm font-medium text-gray-900 mb-1">No attachments</h3>
                <p class="text-sm text-gray-500">
                  Get started by uploading a file or capturing a photo.
                </p>
              </div>

              <div v-else class="space-y-3 max-h-68 overflow-y-auto flex-1">
                <div
                  v-for="file in files"
                  :key="file.id"
                  class="flex items-center justify-between p-4 bg-gray-50 rounded-lg hover:bg-gray-100 transition-colors duration-200"
                >
                  <div class="flex items-center space-x-4 min-w-0 flex-1">
                    <!-- File Thumbnail/Icon -->
                    <div class="flex-shrink-0">
                      <img
                        v-if="file.thumbnail_url && !file.thumbnailError"
                        :src="file.thumbnail_url"
                        :alt="file.filename"
                        class="w-12 h-12 object-cover rounded-lg cursor-pointer hover:opacity-80 transition-opacity duration-200"
                        @click="openImagePreview(file)"
                        @error="() => onImageError(file, 'thumbnail')"
                      />
                      <img
                        v-else-if="isImageJobFile(file) && file.download_url && !file.downloadError"
                        :src="file.download_url"
                        :alt="file.filename"
                        class="w-12 h-12 object-cover rounded-lg cursor-pointer hover:opacity-80 transition-opacity duration-200"
                        @click="openImagePreview(file)"
                        @error="() => onImageError(file, 'download')"
                      />
                      <div
                        v-else
                        class="w-12 h-12 bg-gray-200 rounded-lg flex items-center justify-center transition-colors duration-200"
                        :class="{ 'cursor-pointer hover:bg-gray-300': isPdfFile(file) }"
                        @click="openPdfPreview(file)"
                      >
                        <FileText v-if="isPdfFile(file)" class="w-6 h-6 text-red-600" />
                        <FileIcon v-else class="w-6 h-6 text-gray-600" />
                      </div>
                    </div>

                    <!-- File Info -->
                    <div class="min-w-0 flex-1">
                      <p class="text-sm font-medium text-gray-900 truncate">
                        {{ file.filename }}
                      </p>
                      <div class="flex items-center space-x-2 text-xs text-gray-500 mt-1">
                        <span>{{ formatFileSize(file.size || 0) }}</span>
                        <span>•</span>
                        <span>{{ formatDate(file.uploaded_at) }}</span>
                      </div>
                    </div>
                  </div>

                  <!-- File Actions -->
                  <div class="flex items-center space-x-3">
                    <label class="flex items-center">
                      <input
                        v-model="file.print_on_jobsheet"
                        @change="updatePrintSetting(file)"
                        type="checkbox"
                        class="rounded border-gray-300 text-blue-600 shadow-sm focus:border-blue-300 focus:ring focus:ring-blue-200/50"
                      />
                      <span class="ml-2 text-xs text-gray-600">Print</span>
                    </label>

                    <button
                      @click="downloadFile(file)"
                      class="p-2 text-gray-400 hover:text-blue-600 transition-colors duration-200"
                      title="Download"
                    >
                      <Download class="w-4 h-4" />
                    </button>

                    <button
                      @click="deleteFile(file.id)"
                      class="p-2 text-gray-400 hover:text-red-600 transition-colors duration-200"
                      title="Delete"
                    >
                      <Trash2 class="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>

  <!-- Image Preview Modal -->
  <Dialog :open="isImagePreviewOpen" @update:open="closeImagePreview">
    <DialogContent class="max-w-4xl max-h-[90vh] overflow-auto">
      <DialogHeader>
        <DialogTitle>{{ previewImage?.filename }}</DialogTitle>
        <DialogDescription> Preview of attached image file </DialogDescription>
      </DialogHeader>
      <div class="flex justify-center items-center p-4">
        <img
          v-if="previewImage"
          :src="previewImage.thumbnail_url || previewImage.download_url"
          :alt="previewImage.filename"
          class="max-w-full max-h-[70vh] object-contain rounded-lg shadow-lg"
        />
      </div>
      <DialogFooter>
        <Button @click="downloadFile(previewImage!)" variant="outline">
          <Download class="w-4 h-4 mr-2" />
          Download
        </Button>
        <Button @click="closeImagePreview" variant="secondary"> Close </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>

  <!-- Camera Modal -->
  <CameraModal
    :is-open="isCameraModalOpen"
    @close="closeCameraModal"
    @photo-captured="handlePhotoCaptured"
  />
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { toast } from 'vue-sonner'
import { Camera, Upload, FileText, File as FileIcon, Download, Trash2 } from 'lucide-vue-next'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import CameraModal from './CameraModal.vue'
import { jobService } from '@/services/job.service'
import { schemas } from '@/api/generated/api'
import { formatFileSize, formatDate } from '@/utils/string-formatting'
import type { z } from 'zod'
import { debugLog } from '@/utils/debug'
import axios from '@/plugins/axios'

type JobFile = z.infer<typeof schemas.JobFile> & {
  thumbnailError?: boolean
  downloadError?: boolean
}
type UploadedFileSummary = z.infer<typeof schemas.UploadedFile>

interface Props {
  jobId: string
  jobNumber: number
}

const props = defineProps<Props>()

const emit = defineEmits<{
  'file-uploaded': [file: JobFile]
  'file-deleted': [fileId: string]
}>()

// State
const files = ref<JobFile[]>([])
const uploadProgress = ref(0)
const fileInput = ref<HTMLInputElement>()
const isUploading = ref(false)
const isLoading = ref(false)
const isCameraModalOpen = ref(false)
const isDragOver = ref(false)

// Image preview modal
const previewImage = ref<JobFile | null>(null)
const isImagePreviewOpen = ref(false)

// File loading
async function loadFiles() {
  if (!props.jobId) return

  isLoading.value = true
  try {
    const response = await jobService.listJobFiles(props.jobId)
    files.value = Array.isArray(response) ? response : []
    debugLog('Files loaded successfully:', files.value.length, 'files')
  } catch (error) {
    console.error('❌ Failed to load files:', error)
    toast.error('Failed to load attachments')
    files.value = []
  } finally {
    isLoading.value = false
  }
}

// File input handling
const triggerFileInput = () => {
  if (!isUploading.value) {
    fileInput.value?.click()
  }
}

const handleFileChange = (event: Event) => {
  const target = event.target as HTMLInputElement
  if (target.files) {
    handleFiles(Array.from(target.files))
  }
}

// Drag and drop handling
const handleDragEnter = (event: DragEvent) => {
  event.preventDefault()
  isDragOver.value = true
}

const handleDragOver = (event: DragEvent) => {
  event.preventDefault()
}

const handleDragLeave = (event: DragEvent) => {
  event.preventDefault()
  // Only set to false if we're leaving the drop zone entirely
  if (
    !event.currentTarget ||
    !event.relatedTarget ||
    !(event.currentTarget as Element).contains(event.relatedTarget as Node)
  ) {
    isDragOver.value = false
  }
}

const handleDrop = (event: DragEvent) => {
  event.preventDefault()
  isDragOver.value = false
  if (event.dataTransfer?.files) {
    handleFiles(Array.from(event.dataTransfer.files))
  }
}

// File processing
const handleFiles = async (fileList: File[]) => {
  if (!props.jobNumber) {
    toast.error('Job number is required for file upload')
    return
  }

  const validFiles = fileList.filter((file) => {
    if (file.size === 0) {
      debugLog(`File ${file.name} has 0 bytes and will be ignored`)
      return false
    }
    if (file.size > 10 * 1024 * 1024) {
      // 10MB limit
      toast.error(`File ${file.name} is too large (max 10MB)`)
      return false
    }
    return true
  })

  if (validFiles.length === 0) return

  for (const file of validFiles) {
    await processAndUploadFile(file)
  }
}

const processAndUploadFile = async (file: File) => {
  try {
    let fileToUpload = file

    if (isImageFile(file)) {
      debugLog(`Compressing image before upload: ${file.name}`)
      fileToUpload = await compressImage(file)
    }

    await uploadFile(fileToUpload)
  } catch (error) {
    debugLog(`Error processing file ${file.name}:`, error)
    toast.error(`Failed to upload ${file.name}`)
  }
}

const isImageFile = (file: File): boolean => {
  return file.type.startsWith('image/')
}

const compressImage = (
  file: File,
  maxWidth = 1280,
  maxHeight = 960,
  quality = 0.8,
): Promise<File> => {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.readAsDataURL(file)

    reader.onload = (event) => {
      const img = new Image()
      img.src = event.target?.result as string

      img.onload = () => {
        let { width, height } = img

        if (width > maxWidth || height > maxHeight) {
          const scaleWidth = maxWidth / width
          const scaleHeight = maxHeight / height
          const scaleFactor = Math.min(scaleWidth, scaleHeight)

          width = Math.floor(width * scaleFactor)
          height = Math.floor(height * scaleFactor)
        }

        const canvas = document.createElement('canvas')
        canvas.width = width
        canvas.height = height

        const ctx = canvas.getContext('2d')
        if (!ctx) {
          resolve(file)
          return
        }

        ctx.drawImage(img, 0, 0, width, height)

        canvas.toBlob(
          (blob) => {
            if (!blob) {
              resolve(file)
              return
            }

            const compressedFile = new File([blob], file.name, {
              type: 'image/jpeg',
              lastModified: Date.now(),
            })

            debugLog(`Image compressed: ${file.name}
              Original: ${formatFileSize(file.size)}
              Compressed: ${formatFileSize(compressedFile.size)}`)

            resolve(compressedFile)
          },
          'image/jpeg',
          quality,
        )
      }

      img.onerror = () => reject(new Error('Failed to load image'))
    }

    reader.onerror = () => reject(new Error('Failed to read file'))
  })
}

const uploadFile = async (file: File) => {
  if (!props.jobId) {
    throw new Error('Job ID is required')
  }

  uploadProgress.value = 0
  isUploading.value = true

  try {
    debugLog('Uploading file:', file.name)

    // Simulate upload progress for better UX
    const progressInterval = setInterval(() => {
      if (uploadProgress.value < 90) {
        uploadProgress.value += Math.random() * 20
      }
    }, 200)

    const response = await jobService.uploadJobFiles(props.jobId, [file])

    clearInterval(progressInterval)
    uploadProgress.value = 100

    debugLog('File uploaded successfully:', response)
    toast.success(`File "${file.name}" uploaded successfully`)

    await loadFiles()

    if (response.uploaded.length > 0) {
      const uploadedDescriptor = response.uploaded[0]
      const jobFile = files.value.find((f) => f.id === uploadedDescriptor.id)
      emit('file-uploaded', jobFile ?? mapUploadedToJobFile(uploadedDescriptor))
    }

    // Reset progress after a short delay
    setTimeout(() => {
      uploadProgress.value = 0
    }, 1000)
  } catch (error) {
    debugLog('Error uploading file:', error)
    toast.error(`Failed to upload ${file.name}`)
    throw error
  } finally {
    isUploading.value = false
  }
}

// File actions
async function downloadFile(file: JobFile) {
  if (!file.download_url) {
    toast.error('Download URL not available')
    return
  }

  try {
    // Use axios to ensure cookies are sent with the request for authentication
    const response = await axios.get(file.download_url, {
      responseType: 'blob',
      withCredentials: true, // Explicitly set to ensure cookies are sent
    })

    const blob = response.data
    const url = window.URL.createObjectURL(blob)

    // Open file in new tab for viewing/printing
    const printWindow = window.open(url, '_blank')
    if (printWindow) {
      printWindow.onload = () => {
        // Auto-trigger print dialog after a short delay
        setTimeout(() => {
          printWindow.print()
        }, 500)
      }
    }

    // Also trigger automatic download
    const link = document.createElement('a')
    link.href = url
    link.download = file.filename
    link.style.display = 'none'
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)

    // Clean up the blob URL after a delay
    setTimeout(() => {
      window.URL.revokeObjectURL(url)
    }, 1000)

    debugLog('File opened for printing and download initiated:', file.filename)
  } catch (error) {
    console.error('❌ Error downloading file:', error)
    toast.error('Failed to download file')
  }
}

async function deleteFile(id: string) {
  const file = files.value.find((f) => f.id === id)
  if (!file) return

  if (!confirm(`Are you sure you want to delete "${file.filename}"?`)) return

  // Store original state for rollback
  const originalFiles = [...files.value]

  // Optimistic update - remove from UI immediately
  files.value = files.value.filter((f) => f.id !== id)

  try {
    debugLog('Deleting file:', file.filename)

    const result = await jobService.deleteJobFile(props.jobId, id)

    if (!result.success) {
      throw new Error(result.error || 'Failed to delete file')
    }

    toast.success(`File "${file.filename}" deleted successfully`)
    emit('file-deleted', id)
  } catch (error) {
    console.error('❌ Error deleting file:', error)
    toast.error('Failed to delete file')

    // Rollback optimistic update
    files.value = originalFiles
  }
}

async function updatePrintSetting(file: JobFile) {
  // Store original value for rollback
  const originalValue = file.print_on_jobsheet

  try {
    debugLog('Updating print setting for file:', {
      filename: file.filename,
      print_on_jobsheet: file.print_on_jobsheet,
      job_id: props.jobId,
    })

    const result = await jobService.updateJobFile(props.jobId, file.id, {
      filename: file.filename,
      print_on_jobsheet: file.print_on_jobsheet,
    })

    if (!result.success) {
      throw new Error(result.error || 'Failed to update print setting')
    }

    toast.success(`Print setting updated for "${file.filename}"`)
  } catch (error) {
    console.error('❌ Error updating print setting:', error)
    toast.error('Failed to update print setting')

    // Revert the change
    file.print_on_jobsheet = originalValue
  }
}

// Camera handling
const openCameraModal = () => {
  isCameraModalOpen.value = true
}

const closeCameraModal = () => {
  isCameraModalOpen.value = false
}

const handlePhotoCaptured = async (photo: File) => {
  try {
    debugLog('Photo captured:', {
      name: photo.name,
      size: formatFileSize(photo.size),
      type: photo.type,
    })

    await processAndUploadFile(photo)
    toast.success('Photo uploaded successfully!')
  } catch (error) {
    debugLog('Error uploading captured photo:', error)
    toast.error('Failed to upload photo')
  }
}

// Image preview
const openImagePreview = (file: JobFile) => {
  previewImage.value = file
  isImagePreviewOpen.value = true
}

const closeImagePreview = () => {
  previewImage.value = null
  isImagePreviewOpen.value = false
}

const onImageError = (file: JobFile, type: 'thumbnail' | 'download') => {
  if (type === 'thumbnail') {
    file.thumbnailError = true
  } else {
    file.downloadError = true
  }
  debugLog(`Failed to load image ${type} for file:`, file.filename)
}

// Helper functions
const isImageJobFile = (file: JobFile): boolean => {
  return file.mime_type?.startsWith('image/') || false
}

const isPdfFile = (file: JobFile): boolean => {
  return file.mime_type === 'application/pdf'
}

const openPdfPreview = (file: JobFile) => {
  if (isPdfFile(file) && file.download_url) {
    window.open(file.download_url, '_blank', 'noopener,noreferrer')
  }
}

const mapUploadedToJobFile = (uploaded: UploadedFileSummary): JobFile => ({
  id: uploaded.id,
  filename: uploaded.filename,
  mime_type: undefined,
  uploaded_at: new Date().toISOString(),
  status: undefined,
  print_on_jobsheet: uploaded.print_on_jobsheet,
  size: null,
  download_url: '',
  thumbnail_url: null,
  thumbnailError: false,
  downloadError: false,
})

// Lifecycle
onMounted(() => {
  loadFiles()
})
</script>
