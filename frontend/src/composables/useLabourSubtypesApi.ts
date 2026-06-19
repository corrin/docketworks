import { ref } from 'vue'
import { z } from 'zod'
import { schemas } from '../api/generated/api'
import { api } from '@/api/client'

type LabourSubtype = z.infer<typeof schemas.LabourSubtypeManage>
type LabourSubtypeCreate = z.infer<typeof schemas.LabourSubtypeManageRequest>
type LabourSubtypeUpdate = z.infer<typeof schemas.PatchedLabourSubtypeManageRequest>

export function useLabourSubtypesApi() {
  const error = ref<string | null>(null)

  async function listLabourSubtypes(): Promise<LabourSubtype[]> {
    error.value = null
    try {
      // Manage endpoint returns ALL subtypes, including inactive ones.
      return await api.job_labour_subtypes_manage_list()
    } catch (e: unknown) {
      if (e instanceof Error) {
        error.value = e.message
      } else {
        error.value = 'Failed to fetch labour subtypes.'
      }
      throw e
    }
  }

  async function createLabourSubtype(data: LabourSubtypeCreate): Promise<LabourSubtype> {
    error.value = null
    try {
      return await api.job_labour_subtypes_manage_create(data)
    } catch (e: unknown) {
      if (e instanceof Error) {
        error.value = e.message
      } else {
        error.value = 'Failed to create labour subtype.'
      }
      throw e
    }
  }

  async function retrieveLabourSubtype(id: string): Promise<LabourSubtype> {
    error.value = null
    try {
      return await api.job_labour_subtypes_manage_retrieve({ params: { id } })
    } catch (e: unknown) {
      if (e instanceof Error) {
        error.value = e.message
      } else {
        error.value = 'Failed to fetch labour subtype.'
      }
      throw e
    }
  }

  async function updateLabourSubtype(
    id: string,
    data: LabourSubtypeUpdate,
  ): Promise<LabourSubtype> {
    error.value = null
    try {
      return await api.job_labour_subtypes_manage_partial_update(data, {
        params: { id },
      })
    } catch (e: unknown) {
      if (e instanceof Error) {
        error.value = e.message
      } else {
        error.value = 'Failed to update labour subtype.'
      }
      throw e
    }
  }

  return {
    listLabourSubtypes,
    createLabourSubtype,
    retrieveLabourSubtype,
    updateLabourSubtype,
    error,
  }
}
