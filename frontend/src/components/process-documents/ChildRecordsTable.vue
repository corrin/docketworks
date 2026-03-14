<template>
  <div>
    <h3 class="text-lg font-semibold mb-3">Entries for This Form</h3>

    <!-- Loading -->
    <div v-if="isLoading" class="flex items-center gap-2 py-4 text-muted-foreground">
      <Loader2 class="size-4 animate-spin" />
      Loading entries...
    </div>

    <!-- Empty state -->
    <p v-else-if="children.length === 0" class="text-muted-foreground text-sm py-4">
      No entries yet.
    </p>

    <!-- Table -->
    <div v-else class="border rounded-md overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-muted/50">
          <tr>
            <th class="text-left px-4 py-2 font-medium">Date</th>
            <th class="text-left px-4 py-2 font-medium">Entered By</th>
            <th class="text-left px-4 py-2 font-medium">Created</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="child in children"
            :key="child.id"
            class="border-t hover:bg-muted/30 transition-colors"
          >
            <td class="px-4 py-2">{{ child.entry_date }}</td>
            <td class="px-4 py-2">{{ child.entered_by_name ?? '-' }}</td>
            <td class="px-4 py-2">{{ formatDate(child.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Loader2 } from 'lucide-vue-next'
import { processDocumentsService } from '@/services/processDocuments.service'
import type { FormEntry } from '@/types/processDocument.types'

interface Props {
  formId: string
  category: string
}

const props = defineProps<Props>()

const children = ref<FormEntry[]>([])
const isLoading = ref(false)

onMounted(async () => {
  isLoading.value = true
  try {
    children.value = await processDocumentsService.listEntries(props.category, props.formId)
  } catch (e) {
    console.error('Failed to load entries:', e)
  } finally {
    isLoading.value = false
  }
})

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString()
}
</script>
