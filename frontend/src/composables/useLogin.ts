import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { schemas } from '../api/generated/api'
import type { z } from 'zod'

// Use the existing CustomTokenObtainPair schema for login credentials
type LoginCredentials = z.infer<typeof schemas.CustomTokenObtainPairRequest>

export function useLogin() {
  const router = useRouter()
  const authStore = useAuthStore()

  const credentials = ref<LoginCredentials>({
    username: '',
    password: '',
  })

  const hasError = ref(false)

  const isFormValid = computed(() => {
    const { username, password } = credentials.value
    return username.trim() !== '' && password.trim() !== ''
  })

  const clearError = (): void => {
    hasError.value = false
  }

  const validateForm = (): boolean => {
    if (!isFormValid.value) {
      hasError.value = true
      return false
    }
    return true
  }

  const getRedirectPath = (): string => {
    const redirectQuery = router.currentRoute.value.query.redirect as string
    return redirectQuery || authStore.defaultRoutePath
  }

  const handleLoginSuccess = (): void => {
    const redirectPath = getRedirectPath()
    router.push(redirectPath)
  }

  const handleLoginError = (): void => {
    hasError.value = true
  }

  const handleLogin = async (): Promise<void> => {
    clearError()

    if (!validateForm()) {
      return
    }

    const success = await authStore.login(credentials.value)

    if (success) {
      handleLoginSuccess()
    } else {
      handleLoginError()
    }
  }

  return {
    credentials,
    hasError,
    isFormValid,
    isLoading: computed(() => authStore.isLoading),
    error: computed(() => authStore.error),
    handleLogin,
  }
}
