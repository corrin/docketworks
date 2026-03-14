<template>
  <Dialog :open="isOpen" @update:open="handleModalClose">
    <DialogContent class="sm:max-w-2xl">
      <DialogHeader>
        <DialogTitle>Capture Photo</DialogTitle>
      </DialogHeader>

      <div class="space-y-4">
        <div class="relative bg-black rounded-lg overflow-hidden">
          <video
            ref="videoElement"
            class="w-full h-64 object-cover"
            autoplay
            playsinline
            :style="{ transform: facingMode === 'user' ? 'scaleX(-1)' : 'none' }"
          />

          <div
            v-if="error"
            class="absolute inset-0 flex items-center justify-center bg-black bg-opacity-75 text-white text-center p-4"
          >
            <div>
              <svg
                class="w-12 h-12 mx-auto mb-4 text-red-400"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  stroke-linecap="round"
                  stroke-linejoin="round"
                  stroke-width="2"
                  d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                ></path>
              </svg>
              <p class="text-sm">{{ error }}</p>
            </div>
          </div>

          <div
            v-if="isInitializing"
            class="absolute inset-0 flex items-center justify-center bg-black bg-opacity-75"
          >
            <div class="text-white text-center">
              <div
                class="animate-spin rounded-full h-12 w-12 border-b-2 border-white mx-auto mb-4"
              ></div>
              <p class="text-sm">Starting camera...</p>
            </div>
          </div>
        </div>

        <div class="flex items-center justify-center space-x-4">
          <button
            v-if="hasMultipleCameras"
            @click="switchCamera"
            :disabled="isInitializing"
            class="inline-flex items-center px-3 py-2 border border-gray-300 shadow-sm text-sm leading-4 font-medium rounded-md text-gray-700 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50"
          >
            <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                stroke-linecap="round"
                stroke-linejoin="round"
                stroke-width="2"
                d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"
              ></path>
            </svg>
            Switch Camera
          </button>
        </div>
      </div>

      <DialogFooter>
        <button
          @click="handleCancel"
          type="button"
          class="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500"
        >
          Cancel
        </button>
        <button
          @click="handleCapture"
          :disabled="!isActive || isInitializing"
          type="button"
          class="inline-flex items-center px-4 py-2 text-sm font-medium text-white bg-indigo-600 border border-transparent rounded-md hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-indigo-500 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          <svg class="w-4 h-4 mr-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M3 9a2 2 0 012-2h.93a2 2 0 001.664-.89l.812-1.22A2 2 0 0110.07 4h3.86a2 2 0 011.664.89l.812 1.22A2 2 0 0018.07 7H19a2 2 0 012 2v9a2 2 0 01-2-2V9z"
            ></path>
            <path
              stroke-linecap="round"
              stroke-linejoin="round"
              stroke-width="2"
              d="M15 13a3 3 0 11-6 0 3 3 0 016 0z"
            ></path>
          </svg>
          Capture Photo
        </button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'

import { ref, watch, nextTick, onUnmounted } from 'vue'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { useCamera } from '@/composables/useCamera'

interface Props {
  isOpen: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  close: []
  'photo-captured': [file: File]
}>()

const { isActive, error, startCamera, stopCamera, capturePhoto, compressImage } = useCamera()

const videoElement = ref<HTMLVideoElement>()
const isInitializing = ref(false)
const facingMode = ref<'user' | 'environment'>('environment')
const hasMultipleCameras = ref(false)

watch(
  () => props.isOpen,
  async (open) => {
    if (!open) {
      stopCamera()
      return
    }

    await initializeCamera()
  },
)

const initializeCamera = async () => {
  if (!videoElement.value) {
    await nextTick()
  }

  if (!videoElement.value) {
    error.value = 'Video element not found'
    return
  }

  isInitializing.value = true

  try {
    const devices = await navigator.mediaDevices.enumerateDevices()
    const videoDevices = devices.filter((device) => device.kind === 'videoinput')
    hasMultipleCameras.value = videoDevices.length > 1

    const stream = await startCamera()
    videoElement.value.srcObject = stream
  } catch (err) {
    debugLog('Error initialising camera:', err)
  } finally {
    isInitializing.value = false
  }
}

const switchCamera = async () => {
  if (isInitializing.value) return

  stopCamera()
  facingMode.value = facingMode.value === 'user' ? 'environment' : 'user'
  await initializeCamera()
}

const handleCapture = async () => {
  if (!videoElement.value || !isActive.value) {
    return
  }

  try {
    const photo = await capturePhoto(videoElement.value)
    const compressedPhoto = await compressImage(photo)

    emit('photo-captured', compressedPhoto)
    handleCancel()
  } catch (err) {
    debugLog('Error capturing photo:', err)
    error.value = err instanceof Error ? err.message : 'Error capturing photo'
  }
}

const handleCancel = () => {
  stopCamera()
  emit('close')
}

const handleModalClose = (open: boolean) => {
  if (!open) {
    handleCancel()
  }
}

onUnmounted(() => {
  stopCamera()
})
</script>
