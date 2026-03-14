import { Zodios } from '@zodios/core'
import axios from 'axios'
import { endpoints } from './generated/api'
import { debugLog } from '../utils/debug'
import { trimStringsDeep } from '../utils/sanitize'
import {
  isJobEndpoint,
  isJobMutationEndpoint,
  extractJobId,
  isPoEndpoint,
  isPoMutationEndpoint,
  extractPoId,
  ConcurrencyError,
} from '../types/concurrency'
import { toast } from 'vue-sonner'
import { emitConcurrencyRetry } from '../composables/useConcurrencyEvents'
import { emitPoConcurrencyRetry } from '../composables/usePoConcurrencyEvents'

// Global registry for ETag management to avoid circular imports
let etagManager: {
  getETag: (jobId: string) => string | null
  setETag: (jobId: string, etag: string) => void
} | null = null

let jobReloadManager: {
  reloadJobOnConflict: (jobId: string) => Promise<void>
} | null = null

// Global registry for PO ETag management
let poEtagManager: {
  getETag: (poId: string) => string | null
  setETag: (poId: string, etag: string) => void
} | null = null

let poReloadManager: {
  reloadPoOnConflict: (poId: string) => Promise<void>
} | null = null

// Function to set up the ETag manager after Vue app initialization
export function setupETagManager(manager: {
  getETag: (jobId: string) => string | null
  setETag: (jobId: string, etag: string) => void
}) {
  etagManager = manager
}

// Function to set up the job reload manager after Vue app initialization
export function setupJobReloadManager(manager: {
  reloadJobOnConflict: (jobId: string) => Promise<void>
}) {
  jobReloadManager = manager
}

// Function to set up the PO ETag manager after Vue app initialization
export function setupPoETagManager(manager: {
  getETag: (poId: string) => string | null
  setETag: (poId: string, etag: string) => void
}) {
  poEtagManager = manager
}

// Function to set up the PO reload manager after Vue app initialization
export function setupPoReloadManager(manager: {
  reloadPoOnConflict: (poId: string) => Promise<void>
}) {
  poReloadManager = manager
}

function getApiBaseUrl() {
  if (!import.meta.env.VITE_API_BASE_URL) {
    throw new Error('VITE_API_BASE_URL must be set in environment')
  }
  return import.meta.env.VITE_API_BASE_URL
}

// Configure axios instance for the client
axios.defaults.baseURL = getApiBaseUrl()
axios.defaults.timeout = 60000
axios.defaults.withCredentials = true

// Add ETag interceptors to the client axios instance
axios.interceptors.request.use(
  (config) => {
    // Normalize outbound payloads so every string field is trimmed before hitting the API
    if (config.data !== undefined) {
      config.data = trimStringsDeep(config.data)
    }
    if (config.params !== undefined) {
      config.params = trimStringsDeep(config.params)
    }

    // Add bearer token if using bearer auth
    if (import.meta.env.VITE_AUTH_METHOD === 'bearer') {
      const token = localStorage.getItem('auth_token')
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
      }
    }

    // Add If-Match header for job mutation endpoints
    const url = config.url || ''
    if (isJobMutationEndpoint(url)) {
      const jobId = extractJobId(url)
      if (jobId && etagManager) {
        const etag = etagManager.getETag(jobId)
        if (etag) {
          config.headers['If-Match'] = etag
          debugLog(`[ETags] Added If-Match header for ${url}:`, etag)
        }
      }
    }

    // Add If-Match header for PO mutation endpoints
    if (isPoMutationEndpoint(url)) {
      let poId: string | null = null

      // For delivery receipts, extract PO ID from request body
      if (url.includes('/purchasing/rest/delivery-receipts/')) {
        try {
          const body = typeof config.data === 'string' ? JSON.parse(config.data) : config.data
          poId = body?.purchase_order_id || null
          debugLog(`[PO ETags] Extracted PO ID from delivery receipt body:`, poId)
        } catch (e) {
          debugLog(`[PO ETags] Failed to parse delivery receipt body:`, e)
        }
      } else {
        // For other PO endpoints, extract from URL
        poId = extractPoId(url)
      }

      if (poId && poEtagManager) {
        const etag = poEtagManager.getETag(poId)
        if (etag) {
          config.headers['If-Match'] = etag
          debugLog(`[PO ETags] Added If-Match header for ${url}:`, etag)
        }
      }
    }

    return config
  },
  async (error) => {
    // Handle validation errors (400/422) - DO NOT reload data, let user handle stale data
    // The JobDelta system should handle this by showing proper error messages
    // and allowing user to retry with fresh data if needed
    if (error.response?.status === 400 || error.response?.status === 422) {
      const url = error.config?.url || ''
      const jobId = extractJobId(url)

      if (jobId && isJobMutationEndpoint(url)) {
        debugLog(`[ETags] Validation error for job ${jobId} - letting JobDelta handle it`)
        // JobDelta service will surface the error to user, no silent reload
      }
    }

    return Promise.reject(error)
  },
)

axios.interceptors.response.use(
  (response) => {
    // Capture ETag from job endpoint responses
    const url = response.config.url || ''
    const etag = response.headers['etag']

    if (etag && isJobEndpoint(url)) {
      const jobId = extractJobId(url)
      if (jobId && etagManager) {
        etagManager.setETag(jobId, etag)
        debugLog(`[ETags] Captured ETag for ${url}:`, etag)
      }
    }

    // Capture ETag from PO endpoint responses
    if (etag && isPoEndpoint(url)) {
      const poId = extractPoId(url)
      if (poId && poEtagManager) {
        poEtagManager.setETag(poId, etag)
        debugLog(`[PO ETags] Captured ETag for ${url}:`, etag)
      }
    }

    return response
  },
  async (error) => {
    // Handle concurrency conflicts (412 Precondition Failed)
    if (error.response?.status === 412) {
      const url = error.config?.url || ''
      const jobId = extractJobId(url)
      const poId = extractPoId(url)

      if (jobId && jobReloadManager) {
        debugLog(`[ETags] Concurrency conflict detected for job ${jobId}, reloading data`)

        // Reload job data to get fresh ETag
        try {
          await jobReloadManager.reloadJobOnConflict(jobId)
          debugLog(`[ETags] Successfully reloaded job ${jobId} after concurrency conflict`)
        } catch (reloadError) {
          debugLog(`[ETags] Failed to reload job ${jobId}:`, reloadError)
        }

        // Show persistent user notification with retry option
        toast.error('This job was updated by another user. Data reloaded.', {
          duration: Infinity, // Don't auto-dismiss
          action: {
            label: 'Retry',
            onClick: () => {
              emitConcurrencyRetry(jobId)
            },
          },
        })

        // Create and throw ConcurrencyError
        const concurrencyError = new ConcurrencyError(
          'This job was updated by another user. Data reloaded. Please retry your changes.',
          jobId,
        )

        return Promise.reject(concurrencyError)
      }

      if (poId && poReloadManager) {
        debugLog(`[PO ETags] Concurrency conflict detected for PO ${poId}, reloading data`)

        // Reload PO data to get fresh ETag
        try {
          await poReloadManager.reloadPoOnConflict(poId)
          debugLog(`[PO ETags] Successfully reloaded PO ${poId} after concurrency conflict`)
        } catch (reloadError) {
          debugLog(`[PO ETags] Failed to reload PO ${poId}:`, reloadError)
        }

        // Show persistent user notification with retry option
        toast.error('This purchase order was updated elsewhere. Data reloaded.', {
          duration: Infinity, // Don't auto-dismiss
          action: {
            label: 'Retry',
            onClick: () => {
              emitPoConcurrencyRetry(poId)
            },
          },
        })

        // Create and throw ConcurrencyError
        const concurrencyError = new ConcurrencyError(
          'This purchase order was updated elsewhere. Data reloaded. Please review and resubmit.',
          poId,
        )

        return Promise.reject(concurrencyError)
      }
    }

    // Handle 428 Precondition Required (missing If-Match)
    if (error.response?.status === 428) {
      const url = error.config?.url || ''
      const jobId = extractJobId(url)
      const poId = extractPoId(url)

      if (jobId && jobReloadManager) {
        debugLog(`[ETags] Missing ETag for job ${jobId}, reloading data`)

        // Reload job data to get ETag
        try {
          await jobReloadManager.reloadJobOnConflict(jobId)
          debugLog(`[ETags] Successfully reloaded job ${jobId} to get ETag`)
        } catch (reloadError) {
          debugLog(`[ETags] Failed to reload job ${jobId}:`, reloadError)
        }

        // Show persistent user notification with retry option
        toast.error('Missing version information. Job data reloaded.', {
          duration: Infinity, // Don't auto-dismiss
          action: {
            label: 'Retry',
            onClick: () => {
              emitConcurrencyRetry(jobId)
            },
          },
        })

        // Create and throw ConcurrencyError
        const concurrencyError = new ConcurrencyError(
          'Missing version information. Job data reloaded. Please retry your changes.',
          jobId,
        )

        return Promise.reject(concurrencyError)
      }

      if (poId && poReloadManager) {
        debugLog(`[PO ETags] Missing ETag for PO ${poId}, reloading data`)

        // Reload PO data to get ETag
        try {
          await poReloadManager.reloadPoOnConflict(poId)
          debugLog(`[PO ETags] Successfully reloaded PO ${poId} to get ETag`)
        } catch (reloadError) {
          debugLog(`[PO ETags] Failed to reload PO ${poId}:`, reloadError)
        }

        // Show persistent user notification with retry option
        toast.error(
          'Missing version information. Purchase order data has been reloaded - please review before retrying your update.',
          {
            duration: Infinity, // Don't auto-dismiss
            action: {
              label: 'Retry',
              onClick: () => {
                emitPoConcurrencyRetry(poId)
              },
            },
          },
        )

        // Create and throw ConcurrencyError
        const concurrencyError = new ConcurrencyError(
          'Missing version information. Purchase order data reloaded. Please review and resubmit.',
          poId,
        )

        return Promise.reject(concurrencyError)
      }
    }

    return Promise.reject(error)
  },
)

let _api: InstanceType<typeof Zodios<typeof endpoints>> | null = null

export function getApi(): InstanceType<typeof Zodios<typeof endpoints>> {
  if (!_api) {
    _api = new Zodios(getApiBaseUrl(), endpoints, { axiosInstance: axios })
  }
  return _api
}

export const api = getApi()
