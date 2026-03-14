import { ref } from 'vue'
import { debugLog } from '@/utils/debug'

interface CameraOptions {
  facingMode?: 'user' | 'environment'
  width?: number
  height?: number
  quality?: number
}

export function useCamera(options: CameraOptions = {}) {
  const { facingMode = 'environment', width = 1280, height = 960, quality = 0.85 } = options

  const isActive = ref(false)
  const isModalOpen = ref(false)
  const stream = ref<MediaStream | null>(null)
  const error = ref<string | null>(null)

  const startCamera = async (): Promise<MediaStream> => {
    try {
      error.value = null

      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
        throw new Error('Camera is not supported in this browser')
      }

      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode,
          width: { ideal: width },
          height: { ideal: height },
        },
      })

      stream.value = mediaStream
      isActive.value = true

      return mediaStream
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Unknown error accessing camera'
      error.value = errorMessage
      debugLog('Error starting camera:', err)
      throw new Error(`Could not access camera: ${errorMessage}`)
    }
  }

  const stopCamera = () => {
    if (stream.value) {
      stream.value.getTracks().forEach((track) => track.stop())
      stream.value = null
    }
    isActive.value = false
  }

  const capturePhoto = (videoElement: HTMLVideoElement): Promise<File> => {
    return new Promise((resolve, reject) => {
      try {
        if (!videoElement || videoElement.readyState < 2) {
          reject(new Error('Video is not ready for capture'))
          return
        }

        const canvas = document.createElement('canvas')
        canvas.width = videoElement.videoWidth
        canvas.height = videoElement.videoHeight

        const context = canvas.getContext('2d')
        if (!context) {
          reject(new Error('Could not create canvas context'))
          return
        }

        context.drawImage(videoElement, 0, 0, canvas.width, canvas.height)

        canvas.toBlob(
          (blob) => {
            if (!blob) {
              reject(new Error('Failed to create image'))
              return
            }

            const timestamp = new Date().toISOString().replace(/[:.]/g, '-').split('.')[0]

            const file = new File([blob], `photo-${timestamp}.jpg`, {
              type: 'image/jpeg',
              lastModified: Date.now(),
            })

            resolve(file)
          },
          'image/jpeg',
          quality,
        )
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Unknown capture error'
        reject(new Error(`Error capturing photo: ${errorMessage}`))
      }
    })
  }

  const openCameraModal = () => {
    isModalOpen.value = true
  }

  const closeCameraModal = () => {
    isModalOpen.value = false
    stopCamera()
  }

  const compressImage = (
    file: File,
    maxWidth = 1280,
    maxHeight = 960,
    compressionQuality = 0.7,
  ): Promise<File> => {
    return new Promise((resolve) => {
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
                Original: ${(file.size / 1024 / 1024).toFixed(2)}MB
                Compressed: ${(compressedFile.size / 1024 / 1024).toFixed(2)}MB`)

              resolve(compressedFile)
            },
            'image/jpeg',
            compressionQuality,
          )
        }
      }
    })
  }

  return {
    isActive,
    isModalOpen,
    stream,
    error,
    startCamera,
    stopCamera,
    capturePhoto,
    openCameraModal,
    closeCameraModal,
    compressImage,
  }
}
