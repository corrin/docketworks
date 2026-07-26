import { defineStore } from 'pinia'
import debug from 'debug'

const log = debug('app:feature-flags')

export const useFeatureFlags = defineStore('featureFlags', {
  state: () => ({
    useCostingApi: true,
  }),

  getters: {
    isCostingApiEnabled: (state) => {
      log('Feature flag for costing API:', state.useCostingApi)
      return true
    },
  },
})
