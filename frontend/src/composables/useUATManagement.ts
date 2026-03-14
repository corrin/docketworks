import { ref, computed, onMounted, onUnmounted } from 'vue'
import { awsService, type InstanceStatus } from '@/services/awsService'
import { toast } from 'vue-sonner'

interface ApiError {
  response?: {
    data?: {
      error?: string
      error_code?: string
    }
  }
  message?: string
}

export function useUATManagement() {
  const instanceStatus = ref<InstanceStatus | null>(null)
  const isLoading = ref(false)
  const error = ref<string>('')
  const statusInterval = ref<ReturnType<typeof setInterval> | null>(null)
  const isPolling = ref(false)

  const uatUrl = import.meta.env.VITE_UAT_URL

  // Computed properties for UI states
  const canStart = computed(() => {
    return instanceStatus.value?.state === 'stopped' && !isLoading.value
  })

  const canStop = computed(() => {
    return instanceStatus.value?.state === 'running' && !isLoading.value
  })

  const canReboot = computed(() => {
    return instanceStatus.value?.state === 'running' && !isLoading.value
  })

  const isRunning = computed(() => {
    return instanceStatus.value?.state === 'running'
  })

  const isTransitioning = computed(() => {
    return instanceStatus.value?.state === 'pending' || instanceStatus.value?.state === 'stopping'
  })

  const showStartButton = computed(() => {
    return instanceStatus.value?.state === 'stopped'
  })

  const showStopButton = computed(() => {
    return instanceStatus.value?.state === 'running'
  })

  const showRebootButton = computed(() => {
    return instanceStatus.value?.state === 'running'
  })

  const statusClass = computed(() => {
    switch (instanceStatus.value?.state) {
      case 'running':
        return 'text-green-600 bg-green-100'
      case 'stopped':
        return 'text-red-600 bg-red-100'
      case 'pending':
        return 'text-yellow-600 bg-yellow-100'
      case 'stopping':
        return 'text-orange-600 bg-orange-100'
      case 'terminated':
        return 'text-gray-600 bg-gray-100'
      default:
        return 'text-gray-600 bg-gray-100'
    }
  })

  const statusIcon = computed(() => {
    switch (instanceStatus.value?.state) {
      case 'running':
        return 'CheckCircle'
      case 'stopped':
        return 'XCircle'
      case 'pending':
        return 'Clock'
      case 'stopping':
        return 'Clock'
      case 'terminated':
        return 'AlertTriangle'
      default:
        return 'HelpCircle'
    }
  })

  // Helper functions
  const handleApiError = (error: ApiError) => {
    console.error('API Error:', error)

    if (error.response?.data?.error_code) {
      switch (error.response.data.error_code) {
        case 'InvalidInstance.State':
          return 'Instance is in a transition state. Please wait a moment and try again.'
        case 'UnauthorizedOperation':
          return 'You do not have permission to perform this action.'
        default:
          return error.response.data.error || 'An unknown error occurred.'
      }
    }

    return error.response?.data?.error || error.message || 'An unknown error occurred.'
  }

  const startPolling = () => {
    if (statusInterval.value) {
      clearInterval(statusInterval.value)
    }

    isPolling.value = true
    // Poll every 10 seconds when transitioning, 30 seconds when stable
    const interval = isTransitioning.value ? 10000 : 30000

    statusInterval.value = setInterval(async () => {
      try {
        await refreshStatus()

        // Stop polling if we're in a stable state
        if (!isTransitioning.value && isPolling.value) {
          stopPolling()
        }
      } catch (error) {
        console.error('Error during polling:', error)
      }
    }, interval)
  }

  const stopPolling = () => {
    if (statusInterval.value) {
      clearInterval(statusInterval.value)
      statusInterval.value = null
    }
    isPolling.value = false
  }

  // API methods
  const refreshStatus = async () => {
    try {
      const status = await awsService.getInstanceStatus()
      instanceStatus.value = status
      error.value = ''

      // Start polling if we're in a transitioning state
      if (isTransitioning.value && !isPolling.value) {
        startPolling()
      }
    } catch (err) {
      error.value = handleApiError(err as ApiError)
      toast.error(`Failed to refresh status: ${error.value}`)
    }
  }

  const startInstance = async () => {
    if (!canStart.value) return

    isLoading.value = true
    error.value = ''

    try {
      const result = await awsService.startInstance()

      if (result.success) {
        instanceStatus.value = result
        toast.success('UAT instance start initiated. This may take 2-3 minutes.')
        startPolling()
      } else {
        error.value = result.error || 'Failed to start instance'
        toast.error(error.value)
      }
    } catch (err) {
      error.value = handleApiError(err as ApiError)
      toast.error(`Failed to start instance: ${error.value}`)
    } finally {
      isLoading.value = false
    }
  }

  const stopInstance = async () => {
    if (!canStop.value) return

    isLoading.value = true
    error.value = ''

    try {
      const result = await awsService.stopInstance()

      if (result.success) {
        instanceStatus.value = result
        toast.success('UAT instance stop initiated.')
        startPolling()
      } else {
        error.value = result.error || 'Failed to stop instance'
        toast.error(error.value)
      }
    } catch (err) {
      error.value = handleApiError(err as ApiError)
      toast.error(`Failed to stop instance: ${error.value}`)
    } finally {
      isLoading.value = false
    }
  }

  const rebootInstance = async () => {
    if (!canReboot.value) return

    isLoading.value = true
    error.value = ''

    try {
      const result = await awsService.rebootInstance()

      if (result.success) {
        instanceStatus.value = result
        toast.success('UAT instance reboot initiated.')
        startPolling()
      } else {
        error.value = result.error || 'Failed to reboot instance'
        toast.error(error.value)
      }
    } catch (err) {
      error.value = handleApiError(err as ApiError)
      toast.error(`Failed to reboot instance: ${error.value}`)
    } finally {
      isLoading.value = false
    }
  }

  const openUATSite = () => {
    if (isRunning.value) {
      window.open(uatUrl, '_blank')
    }
  }

  // Lifecycle
  onMounted(() => {
    refreshStatus()
  })

  onUnmounted(() => {
    stopPolling()
  })

  return {
    // State
    instanceStatus,
    isLoading,
    error,
    isPolling,
    uatUrl,

    // Computed
    canStart,
    canStop,
    canReboot,
    isRunning,
    isTransitioning,
    showStartButton,
    showStopButton,
    showRebootButton,
    statusClass,
    statusIcon,

    // Methods
    refreshStatus,
    startInstance,
    stopInstance,
    rebootInstance,
    openUATSite,
    startPolling,
    stopPolling,
  }
}
