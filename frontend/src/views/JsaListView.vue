<template>
  <AppLayout>
    <div class="flex flex-col h-full min-h-0">
      <!-- Header -->
      <div class="flex-shrink-0 bg-white border-b border-gray-200 px-6 py-4">
        <div class="flex items-center justify-between">
          <div>
            <h1 class="text-2xl font-semibold text-gray-900">Job Safety Analyses</h1>
            <p class="text-sm text-gray-500 mt-1">
              View all JSAs across jobs. To create a new JSA, go to the Safety tab on a specific
              job.
            </p>
          </div>
        </div>

        <!-- Search -->
        <div class="mt-4 max-w-md">
          <div class="relative">
            <Search class="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
            <Input
              v-model="searchQuery"
              placeholder="Search by job number or title..."
              class="pl-9"
            />
          </div>
        </div>
      </div>

      <!-- Content -->
      <div class="flex-1 overflow-y-auto p-6 bg-gray-50/50">
        <div class="max-w-5xl mx-auto">
          <!-- Loading State -->
          <div v-if="isLoading" class="flex items-center justify-center py-12">
            <div class="flex flex-col items-center gap-3">
              <Loader2 class="h-8 w-8 animate-spin text-blue-500" />
              <p class="text-sm text-gray-500">Loading JSAs...</p>
            </div>
          </div>

          <!-- Empty State -->
          <div
            v-else-if="filteredDocuments.length === 0 && !searchQuery"
            class="bg-white rounded-lg border border-gray-200 shadow-sm p-12 text-center"
          >
            <ShieldCheck class="mx-auto h-12 w-12 text-gray-400 mb-4" />
            <h3 class="text-lg font-medium text-gray-900 mb-2">No Job Safety Analyses</h3>
            <p class="text-sm text-gray-500 mb-6 max-w-md mx-auto">
              JSAs are created from the Safety tab on individual jobs. Open a job and navigate to
              the Safety tab to create a JSA.
            </p>
            <Button @click="goToKanban" class="gap-2">
              <LayoutDashboard class="w-4 h-4" />
              Go to Kanban Board
            </Button>
          </div>

          <!-- No Results -->
          <div
            v-else-if="filteredDocuments.length === 0 && searchQuery"
            class="bg-white rounded-lg border border-gray-200 shadow-sm p-12 text-center"
          >
            <Search class="mx-auto h-12 w-12 text-gray-400 mb-4" />
            <h3 class="text-lg font-medium text-gray-900 mb-2">No Results Found</h3>
            <p class="text-sm text-gray-500">
              No JSAs match "{{ searchQuery }}". Try a different search term.
            </p>
          </div>

          <!-- Documents List -->
          <div v-else class="space-y-4">
            <div
              v-for="doc in filteredDocuments"
              :key="doc.id"
              class="bg-white rounded-lg border border-gray-200 shadow-sm p-6 hover:shadow-md transition-shadow duration-200"
            >
              <div class="flex items-start justify-between">
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2 mb-2">
                    <ShieldCheck class="w-5 h-5 text-blue-500 flex-shrink-0" />
                    <h3 class="text-lg font-medium text-gray-900 truncate">
                      {{ doc.title }}
                    </h3>
                  </div>
                  <div class="flex items-center gap-4 text-sm text-gray-500">
                    <span v-if="doc.job_number" class="flex items-center gap-1">
                      <Briefcase class="w-4 h-4" />
                      Job {{ doc.job_number }}
                    </span>
                    <span v-if="doc.site_location" class="flex items-center gap-1">
                      <MapPin class="w-4 h-4" />
                      {{ doc.site_location }}
                    </span>
                    <span class="flex items-center gap-1">
                      <Calendar class="w-4 h-4" />
                      {{ formatDate(doc.created_at) }}
                    </span>
                  </div>
                </div>

                <div class="flex items-center gap-2 ml-4">
                  <Button
                    variant="outline"
                    size="sm"
                    @click="openInGoogleDocs(doc)"
                    :disabled="!doc.google_doc_url"
                    class="gap-1"
                  >
                    <ExternalLink class="w-4 h-4" />
                    View
                  </Button>
                </div>
              </div>
            </div>
          </div>

          <!-- Error State -->
          <div
            v-if="error"
            class="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3"
          >
            <AlertCircle class="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
            <div>
              <h4 class="text-sm font-medium text-red-800">Error</h4>
              <p class="text-sm text-red-600">{{ error }}</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import {
  Search,
  ShieldCheck,
  MapPin,
  Calendar,
  ExternalLink,
  AlertCircle,
  Loader2,
  LayoutDashboard,
  Briefcase,
} from 'lucide-vue-next'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useJsaSwpStore } from '@/stores/jsaSwpDocuments'
import type { ProcedureListItem } from '@/types/processDocument.types'
import { formatDate } from '@/utils/string-formatting'

const router = useRouter()
const store = useJsaSwpStore()

// Local state
const searchQuery = ref('')

// Computed
const documents = computed(() => store.jsaDocuments)
const isLoading = computed(() => store.isLoading)
const error = computed(() => store.error)

const filteredDocuments = computed(() => {
  if (!searchQuery.value) return documents.value

  const query = searchQuery.value.toLowerCase()
  return documents.value.filter(
    (doc) =>
      doc.title.toLowerCase().includes(query) ||
      doc.site_location?.toLowerCase().includes(query) ||
      doc.job_number?.toString().includes(query),
  )
})

// Load documents on mount
onMounted(() => {
  loadDocuments()
})

async function loadDocuments() {
  try {
    await store.loadAllJSAs()
  } catch (e) {
    console.error('Failed to load JSAs:', e)
    toast.error('Failed to load job safety analyses')
  }
}

function openInGoogleDocs(doc: ProcedureListItem) {
  if (doc.google_doc_url) {
    window.open(doc.google_doc_url, '_blank')
  }
}

function goToKanban() {
  router.push({ name: 'kanban' })
}
</script>
