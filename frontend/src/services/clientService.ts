import { api } from '../api/client'
import { debugLog } from '../utils/debug'
import { z } from 'zod'
import { schemas } from '../api/generated/api'

type ClientSummary = z.infer<typeof schemas.ClientNameOnly>
type ClientSearchResult = z.infer<typeof schemas.ClientSearchResult>
export type Client = ClientSummary | ClientSearchResult
export type CreateClientData = z.infer<typeof schemas.ClientCreateRequest>
import type { CreateClientResponse } from '@/constants/client-wrapper'

export class ClientService {
  private static instance: ClientService

  static getInstance(): ClientService {
    if (!ClientService.instance) {
      ClientService.instance = new ClientService()
    }
    return ClientService.instance
  }

  async createClient(data: CreateClientData): Promise<CreateClientResponse> {
    try {
      const response = await api.clients_create_create(data)
      return {
        success: true,
        client: response?.client,
      }
    } catch (error: unknown) {
      debugLog('Error creating client:', error)
      return {
        success: false,
        error: 'Failed to create client',
      }
    }
  }

  async getAllClients(): Promise<ClientSummary[]> {
    try {
      const response = await api.clients_all_list()
      return Array.isArray(response) ? response : []
    } catch (error) {
      debugLog('Error fetching clients:', error)
      throw new Error('Failed to load clients')
    }
  }

  searchClients(clientList: Client[], searchTerm: string): Client[] {
    if (!searchTerm.trim()) {
      return clientList
    }

    const term = searchTerm.toLowerCase()
    return clientList.filter((client) => {
      const nameMatch = client.name.toLowerCase().includes(term)
      const emailMatch =
        'email' in client && typeof client.email === 'string'
          ? client.email.toLowerCase().includes(term)
          : false
      const phoneMatch =
        'phone' in client && typeof client.phone === 'string'
          ? client.phone.toLowerCase().includes(term)
          : false
      return nameMatch || emailMatch || phoneMatch
    })
  }
}

export const clientService = ClientService.getInstance()
