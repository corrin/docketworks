import { defineStore } from 'pinia'
import { debugLog } from '@/utils/debug'

export const useFeatureFlags = defineStore('featureFlags', {
  state: () => ({
    useCostingApi: true,
  }),

  getters: {
    isCostingApiEnabled: (state) => {
      debugLog('Feature flag for costing API:', state.useCostingApi)
      return true
    },
  },
})
