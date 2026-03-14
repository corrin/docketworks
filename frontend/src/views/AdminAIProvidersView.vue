<template>
  <AppLayout>
    <div class="p-4 sm:p-8">
      <h1 class="text-2xl font-bold mb-6">AI Provider Configuration</h1>

      <div class="mb-4 flex justify-end">
        <Button @click="openCreateModal">
          <Plus class="w-4 h-4 mr-2" />
          Add New Provider
        </Button>
      </div>

      <div v-if="isLoading" class="text-center py-10">
        <div class="flex items-center justify-center gap-2">
          <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
          AI providers are still loading, please wait
        </div>
      </div>
      <div
        v-else-if="error"
        class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative"
        role="alert"
      >
        <strong class="font-bold">Error:</strong>
        <span class="block sm:inline">{{ error }}</span>
      </div>

      <div v-else class="bg-white rounded-lg shadow overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Provider Type</TableHead>
              <TableHead>Model Name</TableHead>
              <TableHead class="text-center">Is Default</TableHead>
              <TableHead class="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <template v-if="providers.length > 0">
              <TableRow v-for="provider in providers" :key="provider.id">
                <TableCell class="font-medium">{{ provider.name }}</TableCell>
                <TableCell>{{ provider.provider_type }}</TableCell>
                <TableCell class="font-mono text-sm">{{ provider.model_name }}</TableCell>
                <TableCell class="text-center">
                  <Switch
                    :checked="provider.default"
                    @update:checked="() => toggleDefault(provider)"
                    :disabled="provider.default || isTogglingDefault"
                    :aria-label="`Set ${provider.name} as default`"
                  />
                </TableCell>
                <TableCell class="text-right">
                  <div class="flex justify-end space-x-2">
                    <Button variant="outline" size="sm" @click="openEditModal(provider)"
                      >Edit</Button
                    >
                    <Button variant="destructive" size="sm" @click="confirmDelete(provider)"
                      >Delete</Button
                    >
                  </div>
                </TableCell>
              </TableRow>
            </template>
            <template v-else>
              <TableRow>
                <TableCell colspan="5" class="text-center py-10 text-gray-500">
                  No AI providers configured yet.
                </TableCell>
              </TableRow>
            </template>
          </TableBody>
        </Table>
      </div>
    </div>

    <!-- Modals are placed here -->
    <AIProviderFormModal
      v-if="isModalOpen"
      :provider="selectedProvider"
      @close="closeModal"
      @save="handleSave"
    />

    <ConfirmModal
      v-if="isConfirmOpen"
      title="Confirm Deletion"
      :message="`Are you sure you want to delete the provider '${providerToDelete?.name}'? This action cannot be undone.`"
      @confirm="deleteProvider"
      @close="isConfirmOpen = false"
    />
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Plus } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

import AIProviderFormModal from '@/components/admin/AIProviderFormModal.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { AIProviderService } from '@/services/aiProviderService'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type AIProvider = z.infer<typeof schemas.AIProvider>
// api_key is write-only so not on the read schema — extend for form data
type AIProviderFormData = AIProvider & { api_key?: string }

const aiProviderService = AIProviderService.getInstance()

const providers = ref<AIProvider[]>([])
const isLoading = ref(false)
const isTogglingDefault = ref(false)
const error = ref<string | null>(null)

const isModalOpen = ref(false)
const selectedProvider = ref<AIProvider | null>(null)

const isConfirmOpen = ref(false)
const providerToDelete = ref<AIProvider | null>(null)

const fetchProviders = async () => {
  isLoading.value = true
  error.value = null
  try {
    providers.value = await aiProviderService.getProviders()
  } catch {
    const message =
      'Failed to load AI providers. Please check the network connection or backend server.'
    error.value = message
    toast.error(message)
  } finally {
    isLoading.value = false
  }
}

const openCreateModal = () => {
  selectedProvider.value = null
  isModalOpen.value = true
}

const openEditModal = (provider: AIProvider) => {
  selectedProvider.value = { ...provider }
  isModalOpen.value = true
}

const closeModal = () => {
  isModalOpen.value = false
  selectedProvider.value = null
}

const handleSave = async (providerData: AIProviderFormData) => {
  try {
    if (providerData.id) {
      // For update, we need to convert to the update format
      const apiKey = typeof providerData.api_key === 'string' ? providerData.api_key : undefined
      const updateData = {
        name: providerData.name,
        provider_type: providerData.provider_type,
        api_key: apiKey,
        model_name: providerData.model_name,
        default: providerData.default,
      }
      await aiProviderService.updateProvider(Number(providerData.id), updateData)
      toast.success('Provider updated successfully.')
    } else {
      // For create, use the create format
      const apiKey = typeof providerData.api_key === 'string' ? providerData.api_key : undefined
      const createData = {
        name: providerData.name,
        provider_type: providerData.provider_type,
        api_key: apiKey,
        model_name: providerData.model_name,
        default: providerData.default || false,
      }
      console.log('Creating AI provider with data:', createData)
      await aiProviderService.createProvider(createData)
      toast.success('Provider created successfully.')
    }
    closeModal()
    await fetchProviders()
  } catch (error: unknown) {
    const errMessage = (error as Error).message || 'An unknown error occurred.'
    toast.error('Failed to save provider.', {
      description: errMessage,
    })
  }
}

const toggleDefault = async (provider: AIProvider) => {
  if (provider.default || isTogglingDefault.value) return

  isTogglingDefault.value = true
  try {
    await aiProviderService.setDefaultProvider(Number(provider.id), provider)
    toast.success(`'${provider.name}' is now the default provider.`)
    await fetchProviders()
  } catch (error: unknown) {
    const errMessage = (error as Error).message || 'An unknown error occurred.'
    toast.error('Failed to set default provider.', {
      description: errMessage,
    })
  } finally {
    isTogglingDefault.value = false
  }
}

const confirmDelete = (provider: AIProvider) => {
  providerToDelete.value = provider
  isConfirmOpen.value = true
}

const deleteProvider = async () => {
  if (!providerToDelete.value) return
  try {
    await aiProviderService.deleteProvider(Number(providerToDelete.value.id))
    toast.success('Provider deleted successfully.')
    await fetchProviders()
  } catch (error: unknown) {
    const errMessage = (error as Error).message || 'An unknown error occurred.'
    toast.error('Failed to delete provider.', {
      description: errMessage,
    })
  } finally {
    isConfirmOpen.value = false
    providerToDelete.value = null
  }
}

onMounted(() => {
  fetchProviders()
})
</script>
