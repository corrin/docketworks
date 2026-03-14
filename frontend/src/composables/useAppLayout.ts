import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { debugLog } from '../utils/debug'
import type { NavigationItem } from '@/constants/navigation-item'
import { z } from 'zod'
import { schemas } from '../api/generated/api'

type Staff = z.infer<typeof schemas.Staff>

export function useAppLayout() {
  const router = useRouter()
  const authStore = useAuthStore()

  const navigationItems: NavigationItem[] = [
    {
      name: 'kanban',
      to: '/kanban',
      label: 'Kanban',
    },
    {
      name: 'timesheet',
      to: '/timesheet',
      label: 'Timesheet',
    },
  ]

  const userInfo = computed(() => {
    const user = authStore.user as Staff | null
    if (!user) {
      void authStore.initializeAuth()
      return {
        displayName: '',
        email: '',
        is_office_staff: false,
        is_superuser: false,
        first_name: '',
        last_name: '',
        preferred_name: '',
        id: '',
        fullName: '',
      }
    }

    const fullName = authStore.fullName
    return {
      displayName: fullName,
      email: user.email || '',
      is_office_staff: typeof user.is_office_staff === 'boolean' ? user.is_office_staff : false,
      is_superuser: user.is_superuser,
      first_name: user.first_name || '',
      last_name: user.last_name || '',
      preferred_name: user.preferred_name || '',
      id: user.id || '',
      fullName: fullName || '',
    }
  })

  const handleLogout = async (): Promise<void> => {
    try {
      await authStore.logout()
      await router.push('/login')
    } catch (error) {
      debugLog('Logout failed:', error)

      await router.push('/login')
    }
  }

  return {
    navigationItems,
    userInfo,
    handleLogout,
  }
}
