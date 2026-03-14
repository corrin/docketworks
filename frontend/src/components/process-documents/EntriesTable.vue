<template>
  <div>
    <!-- Loading -->
    <div
      v-if="isLoading"
      class="flex items-center gap-2 py-6 text-muted-foreground"
      data-automation-id="EntriesTable-loading"
    >
      <Loader2 class="size-4 animate-spin" />
      Loading entries...
    </div>

    <!-- Empty state -->
    <p
      v-else-if="sortedEntries.length === 0"
      class="text-muted-foreground text-sm py-6"
      data-automation-id="EntriesTable-empty"
    >
      No entries yet. Add the first entry above.
    </p>

    <!-- Table -->
    <div
      v-else
      class="border rounded-md overflow-x-auto"
      data-automation-id="EntriesTable-container"
    >
      <table class="w-full text-sm" data-automation-id="EntriesTable-table">
        <thead class="bg-muted/50">
          <tr>
            <th class="text-left px-4 py-2 font-medium whitespace-nowrap">Date</th>
            <th class="text-left px-4 py-2 font-medium whitespace-nowrap">Entered By</th>
            <th
              v-for="field in schema.fields"
              :key="field.key"
              class="text-left px-4 py-2 font-medium whitespace-nowrap"
            >
              {{ field.label }}
            </th>
            <th class="px-4 py-2 w-12"></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="entry in sortedEntries"
            :key="entry.id"
            class="border-t hover:bg-muted/30 transition-colors"
            :data-automation-id="`EntriesTable-row-${entry.id}`"
          >
            <td class="px-4 py-2 whitespace-nowrap">{{ formatDate(entry.entry_date) }}</td>
            <td class="px-4 py-2 whitespace-nowrap">{{ entry.entered_by_name ?? '-' }}</td>
            <td v-for="field in schema.fields" :key="field.key" class="px-4 py-2">
              {{ formatCellValue(entry, field) }}
            </td>
            <td class="px-4 py-2 text-right">
              <button
                type="button"
                class="inline-flex items-center justify-center rounded-md p-1 text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                title="Edit entry"
                :data-automation-id="`EntriesTable-edit-${entry.id}`"
                @click="emit('edit', entry)"
              >
                <Pencil class="size-4" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Loader2, Pencil } from 'lucide-vue-next'
import type { FormEntry, FormSchema, FormField } from '@/types/processDocument.types'

interface Props {
  entries: FormEntry[]
  schema: FormSchema
  isLoading: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'edit', entry: FormEntry): void
}>()

const sortedEntries = computed(() => {
  return [...props.entries].sort((a, b) => {
    // Sort by entry_date descending (newest first)
    return b.entry_date.localeCompare(a.entry_date)
  })
})

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString()
}

function formatCellValue(entry: FormEntry, field: FormField): string {
  const data = entry.data as Record<string, unknown> | undefined
  if (!data) return '-'

  const value = data[field.key]
  if (value === null || value === undefined || value === '') return '-'

  if (field.type === 'boolean') {
    return value ? '\u2713' : '\u2717'
  }

  if (field.type === 'date' && typeof value === 'string') {
    return new Date(value).toLocaleDateString()
  }

  return String(value)
}
</script>
