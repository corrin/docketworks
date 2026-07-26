import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import debug from 'debug'
import { z } from 'zod'

const log = debug('company:defaults')

type CompanyDefaults = z.infer<typeof schemas.CompanyDefaults>

let cachedDefaults: CompanyDefaults | null = null

export const CompanyDefaultsService = {
  async getDefaults(): Promise<CompanyDefaults> {
    if (cachedDefaults) {
      return cachedDefaults
    }
    try {
      log('Loading company defaults from API...')
      cachedDefaults = await api.company_defaults_retrieve()
      log('Company defaults loaded successfully:', cachedDefaults)
      return cachedDefaults
    } catch (error) {
      log('Failed to load company defaults:', error)
      throw error
    }
  },
  clearCache(): void {
    cachedDefaults = null
  },

  getCached(): CompanyDefaults | null {
    return cachedDefaults
  },
}
