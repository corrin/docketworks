import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'
import { z } from 'zod'

export type AIProvider = z.infer<typeof schemas.AIProvider>
export type AIProviderCreateUpdate = z.infer<typeof schemas.AIProviderCreateUpdateRequest>

export class AIProviderService {
  private static instance: AIProviderService

  public static getInstance(): AIProviderService {
    if (!AIProviderService.instance) {
      AIProviderService.instance = new AIProviderService()
    }
    return AIProviderService.instance
  }

  private constructor() {}

  async getProviders(): Promise<AIProvider[]> {
    try {
      return await api.api_workflow_ai_providers_list()
    } catch (error) {
      debugLog('Failed to fetch AI providers:', error)
      throw error
    }
  }

  async createProvider(providerData: AIProviderCreateUpdate): Promise<AIProvider> {
    try {
      const created = await api.api_workflow_ai_providers_create(providerData)
      return schemas.AIProvider.parse(created)
    } catch (error) {
      debugLog('Failed to create AI provider:', error)
      throw error
    }
  }

  async updateProvider(
    id: number,
    providerData: Partial<AIProviderCreateUpdate>,
  ): Promise<AIProvider> {
    try {
      const updated = await api.api_workflow_ai_providers_partial_update(providerData, {
        params: { id },
      })
      return schemas.AIProvider.parse(updated)
    } catch (error) {
      debugLog(`Failed to update AI provider ${id}:`, error)
      throw error
    }
  }

  async deleteProvider(id: number): Promise<void> {
    try {
      await api.api_workflow_ai_providers_destroy(undefined, { params: { id } })
    } catch (error) {
      debugLog(`Failed to delete AI provider ${id}:`, error)
      throw error
    }
  }

  async getProvider(id: number): Promise<AIProvider> {
    try {
      return await api.api_workflow_ai_providers_retrieve({ params: { id } })
    } catch (error) {
      debugLog(`Failed to get AI provider ${id}:`, error)
      throw error
    }
  }

  async setDefaultProvider(id: number, providerData: AIProvider): Promise<AIProvider> {
    try {
      const response = await api.api_workflow_ai_providers_set_default_create(providerData, {
        params: { id },
      })
      return schemas.AIProvider.parse(response)
    } catch (error) {
      debugLog(`Failed to set default AI provider ${id}:`, error)
      throw error
    }
  }
}

export const aiProviderService = AIProviderService.getInstance()
