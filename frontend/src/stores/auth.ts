import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from '@/plugins/axios'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'
import type { z } from 'zod'

type User = z.infer<typeof schemas.UserProfile>
type LoginCredentials = z.infer<typeof schemas.CustomTokenObtainPairRequest>

interface ErrorResponse {
  detail?: string
  message?: string
  error?: string
  non_field_errors?: string[]
}

interface AxiosErrorResponse {
  status?: number
  data?: ErrorResponse
}

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const hasCheckedSession = ref(false)

  const isAuthenticated = computed(() => !!user.value)

  const fullName = computed(() => {
    if (!user.value) return ''
    return `${user.value.preferred_name || user.value.first_name} ${user.value.last_name}`.trim()
  })

  // Device type controls UI PRESENTATION (which interface to show)
  // This is different from is_office_staff which controls PERMISSIONS
  // The Board page now handles mode switching internally via useBoardMode
  const defaultRoutePath = computed(() => '/kanban')
  const defaultRouteName = computed(() => 'kanban')

  const clearError = (): void => {
    error.value = null
  }

  const setLoading = (loading: boolean): void => {
    isLoading.value = loading
  }

  const setError = (errorMessage: string): void => {
    error.value = errorMessage
  }

  const userIsLogged = async (): Promise<boolean> => {
    try {
      const response = await api.accounts_me_retrieve()
      user.value = response
      return true
    } catch {
      user.value = null
      return false
    } finally {
      hasCheckedSession.value = true
    }
  }

  const login = async (credentials: LoginCredentials): Promise<boolean> => {
    setLoading(true)
    clearError()

    try {
      // Convert reactive object to plain object to avoid Zodios serialization issues
      const plainCredentials = JSON.parse(
        JSON.stringify({
          username: credentials.username,
          password: credentials.password,
        }),
      )

      // Use bearer token auth for ngrok (avoids cookie cross-origin issues)
      if (import.meta.env.VITE_AUTH_METHOD === 'bearer') {
        const response = await api.accounts_api_bearer_token_create(plainCredentials)
        localStorage.setItem('auth_token', response.token)
      } else {
        // Use cookie-based JWT auth for production
        await api.accounts_api_token_create(plainCredentials)
      }

      const userResponse = await api.accounts_me_retrieve()
      user.value = userResponse

      return true
    } catch (err: unknown) {
      user.value = null
      let errorMessage = 'An unexpected login error occurred.'

      if (typeof err === 'object' && err !== null && 'response' in err) {
        const axiosError = err as { response?: AxiosErrorResponse }
        const response = axiosError.response
        const responseData = response?.data || {}
        const detailMessage = responseData.detail || responseData.non_field_errors?.[0]

        if (response?.status === 401 && detailMessage) {
          errorMessage = 'Wrong e-mail or password, please try again.'
        } else if (response?.status && response.status >= 500) {
          errorMessage = 'Server error. Please try again later.'
        } else if (detailMessage) {
          errorMessage = detailMessage
        }
      } else if (typeof err === 'object' && err !== null && 'code' in err) {
        const networkError = err as { code?: string }
        if (networkError.code === 'NETWORK_ERROR' || networkError.code === 'ERR_NETWORK') {
          errorMessage = 'Network error. Please check your internet connection.'
        }
      }

      setError(errorMessage)
      debugLog('Login error:', err)
      return false
    } finally {
      setLoading(false)
    }
  }

  const logout = async (): Promise<void> => {
    try {
      // Clear bearer token if using bearer auth
      if (import.meta.env.VITE_AUTH_METHOD === 'bearer') {
        localStorage.removeItem('auth_token')
      } else {
        // Call backend logout for cookie-based auth
        await axios.post('/accounts/logout/')
      }
    } catch (err) {
      debugLog('Backend logout failed:', err)
    } finally {
      user.value = null
      clearError()
    }
  }

  const initializeAuth = async (): Promise<boolean> => {
    return await userIsLogged()
  }

  return {
    user,
    isLoading,
    error,
    hasCheckedSession,

    isAuthenticated,
    fullName,
    defaultRoutePath,
    defaultRouteName,

    login,
    logout,
    userIsLogged,
    initializeAuth,
  }
})
