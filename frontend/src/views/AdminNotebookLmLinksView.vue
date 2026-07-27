<template>
  <AppLayout>
    <div class="p-4 sm:p-8">
      <h1 class="text-2xl font-bold mb-6">NotebookLM Links</h1>

      <div class="mb-4 flex justify-end">
        <Button @click="openCreateModal">
          <Plus class="w-4 h-4 mr-2" />
          Add New Link
        </Button>
      </div>

      <div v-if="isLoading" class="text-center py-10">
        <div class="flex items-center justify-center gap-2">
          <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
          NotebookLM links are still loading, please wait
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
              <TableHead>URL</TableHead>
              <TableHead class="text-center">Enabled</TableHead>
              <TableHead>Restriction</TableHead>
              <TableHead class="text-center">Order</TableHead>
              <TableHead class="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <template v-if="links.length > 0">
              <TableRow v-for="link in links" :key="link.id">
                <TableCell class="font-medium">{{ link.name }}</TableCell>
                <TableCell class="font-mono text-sm">
                  <a
                    :href="link.url"
                    target="_blank"
                    rel="noopener"
                    class="text-blue-600 hover:underline"
                    >{{ link.url }}</a
                  >
                </TableCell>
                <TableCell class="text-center">{{ link.enabled ? 'Yes' : 'No' }}</TableCell>
                <TableCell>{{
                  link.restriction === 'superuser' ? 'Superusers only' : 'None'
                }}</TableCell>
                <TableCell class="text-center">{{ link.order }}</TableCell>
                <TableCell class="text-right">
                  <div class="flex justify-end space-x-2">
                    <Button variant="outline" size="sm" @click="openEditModal(link)">Edit</Button>
                    <Button variant="destructive" size="sm" @click="confirmDelete(link)"
                      >Delete</Button
                    >
                  </div>
                </TableCell>
              </TableRow>
            </template>
            <template v-else>
              <TableRow>
                <TableCell colspan="6" class="text-center py-10 text-gray-500">
                  No NotebookLM links configured yet.
                </TableCell>
              </TableRow>
            </template>
          </TableBody>
        </Table>
      </div>
    </div>

    <!-- Modals are placed here -->
    <NotebookLmLinkFormModal
      v-if="isModalOpen"
      :link="selectedLink"
      @close="closeModal"
      @save="handleSave"
    />

    <ConfirmModal
      v-if="isConfirmOpen"
      title="Confirm Deletion"
      :message="`Are you sure you want to delete the link '${linkToDelete?.name}'? This action cannot be undone.`"
      @confirm="deleteLink"
      @close="isConfirmOpen = false"
    />
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
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

import NotebookLmLinkFormModal from '@/components/admin/NotebookLmLinkFormModal.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import {
  NotebookLmLinkService,
  type NotebookLmLink,
  type NotebookLmLinkCreateUpdate,
} from '@/services/notebookLmLinkService'
import { useNotebookLmLinksStore } from '@/stores/notebookLmLinks'

const notebookLmLinkService = NotebookLmLinkService.getInstance()

// The navbar renders the shared menu store, which is loaded once at app
// startup — refresh it after every mutation so admin edits show up without
// a page reload.
const notebookLmLinksStore = useNotebookLmLinksStore()

const links = ref<NotebookLmLink[]>([])
const isLoading = ref(false)
const error = ref<string | null>(null)

const isModalOpen = ref(false)
const selectedLink = ref<NotebookLmLink | null>(null)

const isConfirmOpen = ref(false)
const linkToDelete = ref<NotebookLmLink | null>(null)

const fetchLinks = async () => {
  isLoading.value = true
  error.value = null
  try {
    links.value = await notebookLmLinkService.getLinks()
  } catch {
    const message =
      'Failed to load NotebookLM links. Please check the network connection or backend server.'
    error.value = message
    toast.error(message)
  } finally {
    isLoading.value = false
  }
}

const openCreateModal = () => {
  selectedLink.value = null
  isModalOpen.value = true
}

const openEditModal = (link: NotebookLmLink) => {
  selectedLink.value = { ...link }
  isModalOpen.value = true
}

const closeModal = () => {
  isModalOpen.value = false
  selectedLink.value = null
}

const handleSave = async (linkData: NotebookLmLink & NotebookLmLinkCreateUpdate) => {
  try {
    const payload: NotebookLmLinkCreateUpdate = {
      name: linkData.name,
      url: linkData.url,
      enabled: linkData.enabled,
      restriction: linkData.restriction,
      order: linkData.order,
    }
    if (linkData.id) {
      await notebookLmLinkService.updateLink(Number(linkData.id), payload)
      toast.success('Link updated successfully.')
    } else {
      await notebookLmLinkService.createLink(payload)
      toast.success('Link created successfully.')
    }
    closeModal()
    await fetchLinks()
    await notebookLmLinksStore.loadLinks()
  } catch (error: unknown) {
    const errMessage = error instanceof Error ? error.message : 'An unknown error occurred.'
    toast.error('Failed to save link.', {
      description: errMessage,
    })
  }
}

const confirmDelete = (link: NotebookLmLink) => {
  linkToDelete.value = link
  isConfirmOpen.value = true
}

const deleteLink = async () => {
  if (!linkToDelete.value) return
  try {
    await notebookLmLinkService.deleteLink(Number(linkToDelete.value.id))
    toast.success('Link deleted successfully.')
    await fetchLinks()
    await notebookLmLinksStore.loadLinks()
  } catch (error: unknown) {
    const errMessage = error instanceof Error ? error.message : 'An unknown error occurred.'
    toast.error('Failed to delete link.', {
      description: errMessage,
    })
  } finally {
    isConfirmOpen.value = false
    linkToDelete.value = null
  }
}

onMounted(() => {
  fetchLinks()
})
</script>
