/**
 * HELPER FOR AXIOS SETUP - used for manual requests when the generated client is not suitable or is missing some endpoint. It should be slowly replaced by the generated client.
 */

import axios from 'axios'
import { loginXero } from '../composables/useXeroAuth'
import { debugLog } from '@/utils/debug'

// ETag / concurrency handling lives in api/client.ts (Zodios). This helper remains for auth (401/logout) and Xero only.

export const getApiBaseUrl = () => {
  return window.location.origin
}

axios.defaults.baseURL = getApiBaseUrl()
axios.defaults.timeout = 60000
axios.defaults.withCredentials = true

axios.interceptors.request.use(
  (config) => config,
  (error) => Promise.reject(error),
)

axios.interceptors.response.use(
  (response) => {
    return response
  },
  async (error) => {
    const isAuthError = error.response?.status === 401
    if (error.response?.data?.redirect_to_auth) {
      loginXero()
      return Promise.reject(error)
    }

    if (isAuthError) {
      debugLog(
        'API request returned 401; route guard will confirm session state before redirecting',
      )
    }

    return Promise.reject(error)
  },
)

export default axios
