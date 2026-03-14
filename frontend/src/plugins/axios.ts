/**
 * HELPER FOR AXIOS SETUP - used for manual requests when the generated client is not suitable or is missing some endpoint. It should be slowly replaced by the generated client.
 */

import axios from 'axios'
import { useAuthStore } from '@/stores/auth'
import router from '@/router'
import { useXeroAuth } from '../composables/useXeroAuth'
import { debugLog } from '@/utils/debug'

// ETag / concurrency handling lives in api/client.ts (Zodios). This helper remains for auth (401/logout) and Xero only.

export const getApiBaseUrl = () => {
  const env = import.meta.env
  if (!env?.VITE_API_BASE_URL) {
    throw new Error('VITE_API_BASE_URL must be set in environment')
  }
  return env.VITE_API_BASE_URL as string
}

axios.defaults.baseURL = getApiBaseUrl()
axios.defaults.timeout = 60000
axios.defaults.withCredentials = true

axios.interceptors.request.use(
  (config) => {
    // Add bearer token if using bearer auth
    if (import.meta.env.VITE_AUTH_METHOD === 'bearer') {
      const token = localStorage.getItem('auth_token')
      if (token) {
        config.headers.Authorization = `Bearer ${token}`
      }
    }
    return config
  },
  (error) => Promise.reject(error),
)

let isRedirecting = false

axios.interceptors.response.use(
  (response) => {
    return response
  },
  async (error) => {
    const authStore = useAuthStore()
    const isAuthError = error.response?.status === 401
    const currentPath = router.currentRoute.value.path
    const isOnLoginPage = currentPath === '/login'
    if (error.response?.data?.redirect_to_auth) {
      const { loginXero } = useXeroAuth()
      loginXero()
      return Promise.reject(error)
    }

    if (isAuthError && !isOnLoginPage && !isRedirecting) {
      debugLog('Authentication failed - cookies may have expired')

      isRedirecting = true

      try {
        await authStore.logout()

        await router.push({ name: 'login', query: { redirect: currentPath } })
      } catch (redirectError) {
        debugLog('Error during auth redirect:', redirectError)

        window.location.href = '/login'
      } finally {
        setTimeout(() => {
          isRedirecting = false
        }, 1000)
      }
    }

    return Promise.reject(error)
  },
)

export default axios
