import { defineStore } from 'pinia'
import { ref } from 'vue'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'
import type { z } from 'zod'

type XeroItem = z.infer<typeof schemas.XeroItem>

export const useXeroItemStore = defineStore('xeroItems', () => {
  const items = ref<XeroItem[]>([])
  const loading = ref(false)

  async function fetchItems() {
    loading.value = true
    try {
      const response = await api.purchasing_rest_xero_items_retrieve()
      items.value = Array.isArray(response.items) ? response.items : []
      debugLog('Xero items fetched:', items.value)
    } finally {
      loading.value = false
    }
  }

  return { items, loading, fetchItems }
})
