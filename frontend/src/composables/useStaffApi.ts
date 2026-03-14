import { ref } from 'vue'
import { z } from 'zod'
import { schemas } from '../api/generated/api'
import { api } from '@/api/client'
import { toLocalDateString } from '@/utils/dateUtils'

type Staff = z.infer<typeof schemas.Staff>
type StaffCreate = z.infer<typeof schemas.StaffCreateRequest>
type KanbanStaff = z.infer<typeof schemas.KanbanStaff>

export function useStaffApi() {
  const error = ref<string | null>(null)

  async function listStaff(): Promise<Staff[]> {
    error.value = null
    try {
      // Use the regular staff endpoint that returns complete Staff objects
      const result = await api.accounts_api_staff_list()

      // For AdminView, we want to see ALL staff without any filtering
      // Filtering should only be done on Kanban via the backend

      return result
    } catch (e: unknown) {
      if (e instanceof Error) {
        error.value = e.message
      } else {
        error.value = 'Failed to fetch staff.'
      }
      return []
    }
  }

  async function createStaff(data: StaffCreate): Promise<Staff> {
    error.value = null
    try {
      return await api.accounts_api_staff_create(data)
    } catch (e: unknown) {
      if (e instanceof Error) {
        error.value = e.message
      } else {
        error.value = 'Failed to create staff.'
      }
      throw e
    }
  }

  async function updateStaff(id: string | number, data: Record<string, unknown>): Promise<Staff> {
    error.value = null
    try {
      const result = await api.accounts_api_staff_partial_update(
        data as z.infer<typeof schemas.PatchedStaffRequest>,
        {
          params: { id: String(id) },
        },
      )
      return result
    } catch (e: unknown) {
      if (e instanceof Error) {
        error.value = e.message
      } else {
        error.value = 'Failed to update staff.'
      }
      throw e
    }
  }

  async function removeStaff(id: string | number): Promise<void> {
    error.value = null
    try {
      await api.accounts_api_staff_destroy(undefined, { params: { id: String(id) } })
    } catch (e: unknown) {
      if (e instanceof Error) {
        error.value = e.message
      } else {
        error.value = 'Failed to delete staff.'
      }
      throw e
    }
  }

  async function listStaffForKanban(): Promise<KanbanStaff[]> {
    error.value = null
    try {
      // Explicitly pass today's date to avoid backend warning
      // Pass actual_users: 'true' to exclude system/test accounts
      const today = toLocalDateString()
      const result = await api.accounts_api_staff_all_list({
        queries: { date: today, actual_users: 'true' },
      })
      return result
    } catch (e: unknown) {
      if (e instanceof Error) {
        error.value = e.message
      } else {
        error.value = 'Failed to fetch staff for kanban.'
      }
      return []
    }
  }

  return {
    listStaff,
    listStaffForKanban,
    createStaff,
    updateStaff,
    removeStaff,
    error,
  }
}
