import { ref, computed } from 'vue'
import { z } from 'zod'
import { toast } from 'vue-sonner'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'

// Use generated schemas
export type Client = z.infer<typeof schemas.ClientSearchResult>
export type ClientContact = z.infer<typeof schemas.ClientContact>

export function useClientLookup() {
  const searchQuery = ref('')
  const suggestions = ref<Client[]>([])
  const isLoading = ref(false)
  const showSuggestions = ref(false)
  const selectedClient = ref<Client | null>(null)
  const contacts = ref<ClientContact[]>([])

  const hasValidXeroId = computed(() => {
    debugLog('Selected client value: ', selectedClient.value)
    return (
      selectedClient.value?.xero_contact_id != null && selectedClient.value.xero_contact_id !== ''
    )
  })

  const displayValue = computed(() => {
    return selectedClient.value?.name || searchQuery.value
  })

  const searchClients = async (query: string) => {
    if (query.length < 3) {
      suggestions.value = []
      showSuggestions.value = false
      return
    }

    isLoading.value = true

    try {
      const response = await api.clients_search_retrieve({
        queries: { q: query },
      })

      suggestions.value = response.results
      showSuggestions.value = true
    } catch (error) {
      console.error('Error searching clients:', error)
      suggestions.value = []
      showSuggestions.value = false
      toast.error('Failed to search clients')
    } finally {
      isLoading.value = false
    }
  }

  const selectClient = async (client: Client) => {
    selectedClient.value = client
    searchQuery.value = client.name
    showSuggestions.value = false

    contacts.value = []

    await loadClientContacts(client.id)
  }

  const loadClientContacts = async (clientId: string) => {
    try {
      const response = await api.clients_contacts_list({
        queries: { client_id: clientId },
      })
      contacts.value = response || []
    } catch (error) {
      console.error('Error loading client contacts:', error)
      contacts.value = []
      toast.error('Failed to load client contacts')
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
    selectedClient.value = null
    searchQuery.value = ''
    suggestions.value = []
    showSuggestions.value = false
    contacts.value = []
  }

  const resetToInitialState = () => {
    // Only clear if no client is actually selected
    if (!selectedClient.value) {
      searchQuery.value = ''
      suggestions.value = []
      showSuggestions.value = false
      contacts.value = []
    }
  }

  const preserveSelectedClient = (modelValue?: string) => {
    debugLog('Preserving selected client from modelValue:', modelValue)
    // Preserve the selected client when dialog reopens
    if (selectedClient.value && !searchQuery.value) {
      searchQuery.value = selectedClient.value.name
      handleInputChange(selectedClient.value.name)
    }
    if (modelValue && !selectedClient.value) {
      searchQuery.value = modelValue
      handleInputChange(modelValue, true)
    }
  }

  const handleInputChange = (value: string, fromReload = false) => {
    searchQuery.value = value

    if (selectedClient.value && selectedClient.value.name !== value) {
      selectedClient.value = null
      contacts.value = []
    }

    if (value.length >= 3) {
      const searchPromise = searchClients(value)
      if (fromReload) {
        searchPromise
          .then(() => {
            if (!selectedClient.value && suggestions.value.length > 0) {
              const normalizedValue = value.trim().toLowerCase()
              const matchedClient = suggestions.value.find(
                (client) => client.name.trim().toLowerCase() === normalizedValue,
              )

              const clientToSelect = matchedClient ?? suggestions.value[0]
              if (clientToSelect) {
                selectClient(clientToSelect)
              }
            }
          })
          .catch((error) => {
            console.error('Error restoring client selection:', error)
          })
      }
    } else {
      suggestions.value = []
      showSuggestions.value = false
    }
  }

  const createNewClient = (clientName: string) => {
    return clientName.trim()
  }

  const hideSuggestions = () => {
    showSuggestions.value = false
  }

  return {
    searchQuery,
    suggestions,
    isLoading,
    showSuggestions,
    selectedClient,
    contacts,

    hasValidXeroId,
    displayValue,

    searchClients,
    selectClient,
    loadClientContacts,
    getPrimaryContact,
    clearSelection,
    handleInputChange,
    createNewClient,
    hideSuggestions,
    resetToInitialState,
    preserveSelectedClient,
  }
}
