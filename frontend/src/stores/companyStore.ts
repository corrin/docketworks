import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

// Type definitions
type CompanySearchResult = z.infer<typeof schemas.CompanySearchResult>
type CompanySearchResponse = z.infer<typeof schemas.CompanySearchResponse>
type CompanyDetail = z.infer<typeof schemas.CompanyDetailResponse>
type ClientContact = z.infer<typeof schemas.ClientContact>
type CompanyJobsResponse = z.infer<typeof schemas.CompanyJobsResponse>

// Type for company jobs - inferred from generated schema
type CompanyJob = z.infer<typeof schemas.CompanyJobHeader>

export interface FetchCompaniesParams {
  page?: number
  pageSize?: number
  query?: string
  sortBy?: string
  sortDir?: 'asc' | 'desc'
}

export const useCompanyStore = defineStore('companies', () => {
  // State - paginated companies list
  const companies = ref<CompanySearchResult[]>([])
  const page = ref(1)
  const pageSize = ref(50)
  const totalPages = ref(0)
  const totalCount = ref(0)
  const searchQuery = ref('')
  const sortBy = ref<string>('name')
  const sortDir = ref<'asc' | 'desc'>('asc')

  // State - company details and related data
  const detailedCompanies = ref<Record<string, CompanyDetail>>({})
  const companyContacts = ref<Record<string, ClientContact[]>>({})
  const companyJobs = ref<Record<string, CompanyJob[]>>({})
  const isLoading = ref(false)
  const isLoadingDetail = ref(false)
  const isLoadingContacts = ref(false)
  const isLoadingJobs = ref(false)

  // Getters
  const hasCompanies = computed(() => companies.value.length > 0)

  /**
   * Fetch companies with server-side pagination, search, and sorting
   */
  async function fetchCompanies(params: FetchCompaniesParams = {}) {
    isLoading.value = true

    // Update local state from params
    if (params.page !== undefined) page.value = params.page
    if (params.pageSize !== undefined) pageSize.value = params.pageSize
    if (params.query !== undefined) searchQuery.value = params.query
    if (params.sortBy !== undefined) sortBy.value = params.sortBy
    if (params.sortDir !== undefined) sortDir.value = params.sortDir

    try {
      const response: CompanySearchResponse = await api.companies_search_retrieve({
        queries: {
          page: page.value,
          page_size: pageSize.value,
          q: searchQuery.value || undefined,
          sort_by: sortBy.value,
          sort_dir: sortDir.value,
        },
      })
      companies.value = response.results
      totalCount.value = response.count
      totalPages.value = response.total_pages
      page.value = response.page
      pageSize.value = response.page_size
    } catch (error) {
      console.error('Failed to fetch companies:', error)
      companies.value = []
      throw error
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Fetch detailed information for a specific company
   * @param companyId UUID of the company
   */
  async function fetchCompanyDetail(companyId: string) {
    isLoadingDetail.value = true

    try {
      const response = await api.companies_retrieve({
        params: { company_id: companyId },
      })
      detailedCompanies.value[companyId] = response
      return response
    } catch (error) {
      console.error('Failed to fetch company details:', error)
      throw error
    } finally {
      isLoadingDetail.value = false
    }
  }

  /**
   * Fetch contacts for a specific company
   * @param companyId UUID of the company
   */
  async function fetchClientContacts(companyId: string) {
    isLoadingContacts.value = true

    try {
      const response = await api.companies_contacts_list({
        queries: { company_id: companyId },
      })
      companyContacts.value[companyId] = response
      return response
    } catch (error) {
      console.error('Failed to fetch company contacts:', error)
      companyContacts.value[companyId] = []
      throw error
    } finally {
      isLoadingContacts.value = false
    }
  }

  /**
   * Get cached company detail or fetch if not available
   * @param companyId UUID of the company
   */
  async function getCompanyDetail(companyId: string): Promise<CompanyDetail> {
    if (detailedCompanies.value[companyId]) {
      return detailedCompanies.value[companyId]
    }
    return await fetchCompanyDetail(companyId)
  }

  /**
   * Get cached company contacts or fetch if not available
   * @param companyId UUID of the company
   */
  async function getClientContacts(companyId: string): Promise<ClientContact[]> {
    if (companyContacts.value[companyId]) {
      return companyContacts.value[companyId]
    }
    return await fetchClientContacts(companyId)
  }

  /**
   * Fetch jobs for a specific company
   * @param companyId UUID of the company
   */
  async function fetchCompanyJobs(companyId: string) {
    isLoadingJobs.value = true

    try {
      const response: CompanyJobsResponse = await api.companies_jobs_retrieve({
        params: { company_id: companyId },
      })
      companyJobs.value[companyId] = response.results
      return response.results
    } catch (error) {
      console.error('Failed to fetch company jobs:', error)
      companyJobs.value[companyId] = []
      throw error
    } finally {
      isLoadingJobs.value = false
    }
  }

  /**
   * Get cached company jobs or fetch if not available
   * @param companyId UUID of the company
   */
  async function getCompanyJobs(companyId: string): Promise<CompanyJob[]> {
    if (companyJobs.value[companyId]) {
      return companyJobs.value[companyId]
    }
    return await fetchCompanyJobs(companyId)
  }

  /**
   * Clear all cached data
   */
  function clearCache() {
    companies.value = []
    detailedCompanies.value = {}
    companyContacts.value = {}
    companyJobs.value = {}
    searchQuery.value = ''
    page.value = 1
    totalPages.value = 0
    totalCount.value = 0
  }

  return {
    // State - paginated companies
    companies,
    page,
    pageSize,
    totalPages,
    totalCount,
    searchQuery,
    sortBy,
    sortDir,

    // State - other
    detailedCompanies,
    companyContacts,
    companyJobs,
    isLoading,
    isLoadingDetail,
    isLoadingContacts,
    isLoadingJobs,

    // Getters
    hasCompanies,

    // Actions
    fetchCompanies,
    fetchCompanyDetail,
    fetchClientContacts,
    fetchCompanyJobs,
    getCompanyDetail,
    getClientContacts,
    getCompanyJobs,
    clearCache,
  }
})
