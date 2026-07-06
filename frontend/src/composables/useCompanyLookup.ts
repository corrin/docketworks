import { ref, computed } from 'vue'
import { z } from 'zod'
import { toast } from 'vue-sonner'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'
import { logSearchResultClick } from '@/services/searchTelemetry.service'

// Use generated schemas, excluding scalar phone fields now owned by contact methods.
export type Company = Omit<z.infer<typeof schemas.CompanySearchResult>, 'phone'>
export type ClientContact = Omit<z.infer<typeof schemas.ClientContact>, 'phone'>

type UseCompanyLookupOptions = {
  supplierLookup?: { value: boolean }
}

export async function logCompanySearchClick(
  company: Company,
  query: string,
  rank: number | null,
  source = 'client_lookup',
) {
  const trimmedQuery = query.trim()
  if (trimmedQuery.length < 3) {
    return
  }

  try {
    await logSearchResultClick({
      domain: 'client',
      query: trimmedQuery,
      selectedResultId: company.id,
      selectedLabel: company.name,
      selectedRank: rank,
      source,
    })
  } catch (error) {
    debugLog('Failed to log company search click:', error)
  }
}

export function useCompanyLookup(options: UseCompanyLookupOptions = {}) {
  const searchQuery = ref('')
  const suggestions = ref<Company[]>([])
  const isLoading = ref(false)
  const showSuggestions = ref(false)
  const selectedCompany = ref<Company | null>(null)
  const contacts = ref<ClientContact[]>([])

  const hasValidXeroId = computed(() => {
    debugLog('Selected company value: ', selectedCompany.value)
    return (
      selectedCompany.value?.xero_contact_id != null && selectedCompany.value.xero_contact_id !== ''
    )
  })

  const displayValue = computed(() => {
    return selectedCompany.value?.name || searchQuery.value
  })

  const searchCompanies = async (query: string) => {
    if (query.length < 3) {
      suggestions.value = []
      showSuggestions.value = false
      return
    }

    isLoading.value = true

    try {
      const response = options.supplierLookup?.value
        ? await api.purchasing_suppliers_search_retrieve({
            queries: { q: query },
          })
        : await api.companies_search_retrieve({
            queries: { q: query },
          })

      suggestions.value = response.results
      showSuggestions.value = true
    } catch (error) {
      console.error('Error searching companies:', error)
      suggestions.value = []
      showSuggestions.value = false
      toast.error('Failed to search companies')
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Button-triggered company search: no minimum query length, first page of
   * results sorted by name. Results land in `suggestions` (same as the
   * typeahead search) for select-style pickers.
   */
  const browseCompanies = async () => {
    if (options.supplierLookup?.value) {
      throw new Error('browseCompanies does not support supplier lookup')
    }

    isLoading.value = true

    try {
      const response = await api.companies_search_retrieve({
        queries: {
          page: 1,
          page_size: 20,
          q: searchQuery.value || undefined,
          sort_by: 'name',
          sort_dir: 'asc',
        },
      })
      suggestions.value = response.results || []
    } catch (error) {
      console.error('Error searching companies:', error)
      suggestions.value = []
      toast.error('Failed to search companies')
    } finally {
      isLoading.value = false
    }
  }

  /**
   * Logs search telemetry for a selection made from `suggestions` by id
   * (select-style pickers where the user picks from a dropdown of results).
   */
  const logSelectedCompanyClick = (companyId: string, source: string) => {
    const index = suggestions.value.findIndex((company) => company.id === companyId)
    const company = suggestions.value[index]
    if (!company) return
    void logCompanySearchClick(company, searchQuery.value, index + 1, source)
  }

  const selectCompany = async (company: Company) => {
    selectedCompany.value = company
    searchQuery.value = company.name
    showSuggestions.value = false

    contacts.value = []

    await loadClientContacts(company.id)
  }

  const loadClientContacts = async (companyId: string) => {
    if (!companyId) {
      contacts.value = []
      return
    }

    try {
      const response = await api.companies_contacts_list({
        queries: { company_id: companyId },
      })
      contacts.value = response || []
    } catch (error) {
      console.error('Error loading company contacts:', error)
      contacts.value = []
      toast.error('Failed to load company contacts')
    }
  }

  const getPrimaryContact = (): ClientContact | null => {
    if (contacts.value.length === 0) {
      return null
    }

    const primaryContact = contacts.value.find((contact) => contact.is_primary)

    return primaryContact || contacts.value[0]
  }

  const clearSelection = () => {
    selectedCompany.value = null
    searchQuery.value = ''
    suggestions.value = []
    showSuggestions.value = false
    contacts.value = []
  }

  const resetToInitialState = () => {
    // Only clear if no company is actually selected
    if (!selectedCompany.value) {
      searchQuery.value = ''
      suggestions.value = []
      showSuggestions.value = false
      contacts.value = []
    }
  }

  const preserveSelectedCompany = (modelValue?: string) => {
    debugLog('Preserving selected company from modelValue:', modelValue)
    // Preserve the selected company when dialog reopens
    if (selectedCompany.value && !searchQuery.value) {
      searchQuery.value = selectedCompany.value.name
      handleInputChange(selectedCompany.value.name)
    }
    if (modelValue && !selectedCompany.value) {
      searchQuery.value = modelValue
      handleInputChange(modelValue, true)
    }
  }

  const handleInputChange = (value: string, fromReload = false) => {
    searchQuery.value = value

    if (selectedCompany.value && selectedCompany.value.name !== value) {
      selectedCompany.value = null
      contacts.value = []
    }

    if (value.length >= 3) {
      const searchPromise = searchCompanies(value)
      if (fromReload) {
        searchPromise
          .then(() => {
            if (!selectedCompany.value && suggestions.value.length > 0) {
              const normalizedValue = value.trim().toLowerCase()
              const matchedCompany = suggestions.value.find(
                (company) => company.name.trim().toLowerCase() === normalizedValue,
              )

              const companyToSelect = matchedCompany ?? suggestions.value[0]
              if (companyToSelect) {
                selectCompany(companyToSelect)
              }
            }
          })
          .catch((error) => {
            console.error('Error restoring company selection:', error)
          })
      }
    } else {
      suggestions.value = []
      showSuggestions.value = false
    }
  }

  const createNewCompany = (companyName: string) => {
    return companyName.trim()
  }

  const hideSuggestions = () => {
    showSuggestions.value = false
  }

  return {
    searchQuery,
    suggestions,
    isLoading,
    showSuggestions,
    selectedCompany,
    contacts,

    hasValidXeroId,
    displayValue,

    searchCompanies,
    browseCompanies,
    logSelectedCompanyClick,
    selectCompany,
    loadClientContacts,
    getPrimaryContact,
    clearSelection,
    handleInputChange,
    createNewCompany,
    hideSuggestions,
    resetToInitialState,
    preserveSelectedCompany,
  }
}
