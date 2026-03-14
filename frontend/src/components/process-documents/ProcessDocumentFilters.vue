<template>
  <div class="flex flex-col gap-4">
    <div class="flex flex-wrap items-center gap-4">
      <!-- Tag pills -->
      <div
        v-if="availableTags.length > 0"
        class="flex flex-wrap gap-1.5"
        data-automation-id="ProcessDocumentFilters-tags"
      >
        <Badge
          v-for="tag in availableTags"
          :key="tag"
          :variant="filters.tags.includes(tag) ? 'default' : 'outline'"
          class="cursor-pointer select-none"
          :data-automation-id="`ProcessDocumentFilters-tag-${tag}`"
          @click="toggleTag(tag)"
        >
          {{ tag }}
        </Badge>
      </div>

      <!-- Status dropdown -->
      <select
        :value="filters.status"
        class="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] outline-none"
        data-automation-id="ProcessDocumentFilters-status"
        @change="onStatusChange"
      >
        <option value="active">Active</option>
        <option value="draft">Draft</option>
        <option value="completed">Completed</option>
        <option value="archived">Archived</option>
        <option value="all">All</option>
      </select>

      <!-- Search input -->
      <div class="ml-auto min-w-[200px]">
        <Input
          :model-value="searchInput"
          placeholder="Search documents..."
          data-automation-id="ProcessDocumentFilters-search"
          @update:model-value="onSearchInput"
        />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import type { ProcessDocumentFilters } from '@/types/processDocument.types'
import Badge from '@/components/ui/badge/Badge.vue'
import Input from '@/components/ui/input/Input.vue'

interface Props {
  filters: ProcessDocumentFilters
  availableTags: string[]
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'update:filters', value: ProcessDocumentFilters): void
}>()

// Local search input for debounce
const searchInput = ref(props.filters.search)
let searchTimeout: ReturnType<typeof setTimeout> | null = null

// Sync local search when prop changes externally
watch(
  () => props.filters.search,
  (newVal) => {
    searchInput.value = newVal
  },
)

function updateFilter<K extends keyof ProcessDocumentFilters>(
  key: K,
  value: ProcessDocumentFilters[K],
) {
  emit('update:filters', { ...props.filters, [key]: value })
}

function toggleTag(tag: string) {
  const current = props.filters.tags
  const next = current.includes(tag) ? current.filter((t) => t !== tag) : [...current, tag]
  updateFilter('tags', next)
}

function onStatusChange(event: Event) {
  const value = (event.target as HTMLSelectElement).value
  updateFilter('status', value)
}

function onSearchInput(value: string | number) {
  searchInput.value = String(value)

  if (searchTimeout) {
    clearTimeout(searchTimeout)
  }

  searchTimeout = setTimeout(() => {
    updateFilter('search', String(value))
  }, 300)
}
</script>
