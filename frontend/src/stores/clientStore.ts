import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

// Type definitions
type ClientSearchResult = z.infer<typeof schemas.ClientSearchResult>
type ClientSearchResponse = z.infer<typeof schemas.ClientSearchResponse>
type ClientDetail = z.infer<typeof schemas.ClientDetailResponse>
type ClientContact = z.infer<typeof schemas.ClientContact>
type ClientJobsResponse = z.infer<typeof schemas.ClientJobsResponse>

// Type for client jobs - inferred from generated schema
type ClientJob = z.infer<typeof schemas.ClientJobHeader>

export interface FetchClientsParams {
  page?: number
  pageSize?: number
  query?: string
  sortBy?: string
  sortDir?: 'asc' | 'desc'
}

export const useClientStore = defineStore('clients', () => {
  // State - paginated clients list
  const clients = ref<ClientSearchResult[]>([])
  const page = ref(1)
  const pageSize = ref(50)
  const totalPages = ref(0)
  const totalCount = ref(0)
  const searchQuery = ref('')
  const sortBy = ref<string>('name')
  const sortDir = ref<'asc' | 'desc'>('asc')

  // State - client details and related data
  const detailedClients = ref<Record<string, ClientDetail>>({})
  const clientContacts = ref<Record<string, ClientContact[]>>({})
  const clientJobs = ref<Record<string, ClientJob[]>>({})
  const isLoading = ref(false)
  const isLoadingDetail = ref(false)
  const isLoadingContacts = ref(false)
  const isLoadingJobs = ref(false)

  // Getters
  const hasClients = computed(() => clients.value.length > 0)

  /**
   * Fetch clients with server-side pagination, search, and sorting
   */
  async function fetchClients(params: FetchClientsParams = {}) {
    isLoading.value = true

    // Update local state from params
    if (params.page !== undefined) page.value = params.page
    if (params.pageSize !== undefined) pageSize.value = params.pageSize
    if (params.query !== undefined) searchQuery.value = params.query
    if (params.sortBy !== undefined) sortBy.value = params.sortBy
    if (params.sortDir !== undefined) sortDir.value = params.sortDir

    try {
      const response: ClientSearchResponse = await api.clients_search_retrieve({
        queries: {
          page: page.value,
          page_size: pageSize.value,
          q: searchQuery.value || undefined,
          sort_by: sortBy.value,
          sort_dir: sortDir.value,
        },
      })
      clients.value = response.results || []
      totalCount.value = response.count
      totalPages.value = response.total_pages
      page.value = response.page
      pageSize.value = response.page_size
    } catch (error) {
      console.error('Failed to fetch clients:', error)
      clients.value = []
      throw error
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Fetch detailed information for a specific client
   * @param clientId UUID of the client
   */
  async function fetchClientDetail(clientId: string) {
    isLoadingDetail.value = true

    try {
      const response = await api.clients_retrieve({
        params: { client_id: clientId },
      })
      detailedClients.value[clientId] = response
      return response
    } catch (error) {
      console.error('Failed to fetch client details:', error)
      throw error
    } finally {
      isLoadingDetail.value = false
    }
  }

  /**
   * Fetch contacts for a specific client
   * @param clientId UUID of the client
   */
  async function fetchClientContacts(clientId: string) {
    isLoadingContacts.value = true

    try {
      const response = await api.clients_contacts_list({
        queries: { client_id: clientId },
      })
      clientContacts.value[clientId] = response || []
      return response || []
    } catch (error) {
      console.error('Failed to fetch client contacts:', error)
      clientContacts.value[clientId] = []
      throw error
    } finally {
      isLoadingContacts.value = false
    }
  }

  /**
   * Get cached client detail or fetch if not available
   * @param clientId UUID of the client
   */
  async function getClientDetail(clientId: string): Promise<ClientDetail> {
    if (detailedClients.value[clientId]) {
      return detailedClients.value[clientId]
    }
    return await fetchClientDetail(clientId)
  }

  /**
   * Get cached client contacts or fetch if not available
   * @param clientId UUID of the client
   */
  async function getClientContacts(clientId: string): Promise<ClientContact[]> {
    if (clientContacts.value[clientId]) {
      return clientContacts.value[clientId]
    }
    return await fetchClientContacts(clientId)
  }

  /**
   * Fetch jobs for a specific client
   * @param clientId UUID of the client
   */
  async function fetchClientJobs(clientId: string) {
    isLoadingJobs.value = true

    try {
      const response: ClientJobsResponse = await api.clients_jobs_retrieve({
        params: { client_id: clientId },
      })
      clientJobs.value[clientId] = response.results || []
      return response.results || []
    } catch (error) {
      console.error('Failed to fetch client jobs:', error)
      clientJobs.value[clientId] = []
      throw error
    } finally {
      isLoadingJobs.value = false
    }
  }

  /**
   * Get cached client jobs or fetch if not available
   * @param clientId UUID of the client
   */
  async function getClientJobs(clientId: string): Promise<ClientJob[]> {
    if (clientJobs.value[clientId]) {
      return clientJobs.value[clientId]
    }
    return await fetchClientJobs(clientId)
  }

  /**
   * Clear all cached data
   */
  function clearCache() {
    clients.value = []
    detailedClients.value = {}
    clientContacts.value = {}
    clientJobs.value = {}
    searchQuery.value = ''
    page.value = 1
    totalPages.value = 0
    totalCount.value = 0
  }

  return {
    // State - paginated clients
    clients,
    page,
    pageSize,
    totalPages,
    totalCount,
    searchQuery,
    sortBy,
    sortDir,

    // State - other
    detailedClients,
    clientContacts,
    clientJobs,
    isLoading,
    isLoadingDetail,
    isLoadingContacts,
    isLoadingJobs,

    // Getters
    hasClients,

    // Actions
    fetchClients,
    fetchClientDetail,
    fetchClientContacts,
    fetchClientJobs,
    getClientDetail,
    getClientContacts,
    getClientJobs,
    clearCache,
  }
})
