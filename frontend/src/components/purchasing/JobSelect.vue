<template>
  <div class="relative" ref="containerRef">
    <!-- Input field -->
    <input
      ref="inputRef"
      v-model="searchTerm"
      type="text"
      :placeholder="placeholder"
      :disabled="disabled"
      data-automation-id="JobSelect-job-search"
      class="w-full px-3 py-2 border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
      :class="{
        'border-red-500': hasError,
        'opacity-50 cursor-not-allowed': disabled,
      }"
      @focus="disabled ? null : onFocus()"
      @blur="disabled ? null : onBlur($event)"
      @input="disabled ? null : onInput()"
      @keydown="disabled ? null : onKeydown($event)"
    />

    <!-- Error message -->
    <div v-if="hasError && errorMessage" class="text-red-500 text-sm mt-1">
      {{ errorMessage }}
    </div>

    <!-- Dropdown - Teleported to body to avoid overflow clipping -->
    <Teleport to="body">
      <div
        v-if="showDropdown && !disabled"
        ref="dropdownRef"
        :style="dropdownStyle"
        data-automation-id="JobSelect-dropdown"
        class="fixed z-[9999] bg-white border border-gray-300 rounded-md shadow-lg max-h-60 overflow-y-auto"
      >
        <!-- Job items -->
        <div
          v-for="(job, index) in filteredJobs"
          :key="job.id"
          :data-automation-id="`JobSelect-option-${job.job_number}`"
          :class="{
            'bg-blue-50': index === highlightedIndex,
            'hover:bg-gray-50': index !== highlightedIndex,
          }"
          class="px-3 py-2 cursor-pointer border-b border-gray-100 last:border-b-0"
          @click="selectJob(job)"
          @mouseenter="highlightedIndex = index"
        >
          <div class="font-medium text-gray-900">
            <span v-if="isStockHoldingJob(job)" class="mr-1">📦</span>
            {{ job.job_number }}
          </div>
          <div class="text-sm text-gray-600 truncate">
            {{ job.description || job.name || job.job_display_name }}
          </div>
          <div
            v-if="job.client_name && !isStockHoldingJob(job)"
            class="text-xs text-gray-500 truncate"
          >
            Client: {{ job.client_name }}
          </div>
          <div v-if="isStockHoldingJob(job)" class="text-xs text-orange-600 truncate">
            Stock Holding Job
          </div>
        </div>

        <!-- Loading message -->
        <div v-if="isLoading" class="px-3 py-2 text-gray-500 text-sm flex items-center gap-2">
          <div class="animate-spin rounded-full h-3 w-3 border-b-2 border-blue-500"></div>
          Jobs are loading, please wait
        </div>

        <!-- No results message -->
        <div
          v-if="!isLoading && filteredJobs.length === 0 && searchTerm.trim()"
          class="px-3 py-2 text-gray-500 text-sm"
        >
          No jobs found for "{{ searchTerm }}"
        </div>

        <!-- No jobs available -->
        <div
          v-if="!isLoading && filteredJobs.length === 0 && !searchTerm.trim()"
          class="px-3 py-2 text-gray-500 text-sm"
        >
          No jobs available
        </div>
      </div>
    </Teleport>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { z } from 'zod'
import { schemas } from '../../api/generated/api'

type Job = z.infer<typeof schemas.JobForPurchasing> & {
  description?: string | null
}

const props = defineProps<{
  modelValue?: string | number | null
  jobs?: Job[]
  placeholder?: string
  hasError?: boolean
  errorMessage?: string
  isLoading?: boolean
  disabled?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string | null]
  jobSelected: [job: Job | null]
}>()

const inputRef = ref<HTMLInputElement | null>(null)
const dropdownRef = ref<HTMLDivElement | null>(null)
const containerRef = ref<HTMLDivElement | null>(null)
const searchTerm = ref('')
const showDropdown = ref(false)
const highlightedIndex = ref(-1)
const dropdownPosition = ref({ top: 0, left: 0, width: 0 })

// Compute dropdown style for fixed positioning
const dropdownStyle = computed(() => ({
  top: `${dropdownPosition.value.top}px`,
  left: `${dropdownPosition.value.left}px`,
  width: `${dropdownPosition.value.width}px`,
}))

// Update dropdown position based on input element
const updateDropdownPosition = () => {
  if (!inputRef.value) return
  const rect = inputRef.value.getBoundingClientRect()
  dropdownPosition.value = {
    top: rect.bottom + 4,
    left: rect.left,
    width: rect.width,
  }
}

const filteredJobs = computed(() => {
  const excludedStatuses = ['rejected', 'archived', 'completed']
  const availableJobs = (props.jobs || []).filter(
    (job: Job) => !excludedStatuses.includes(job.status?.toLowerCase() || ''),
  )

  if (!searchTerm.value.trim()) {
    return availableJobs
  }

  const term = searchTerm.value.toLowerCase()

  const filtered = availableJobs.filter((job: Job) => {
    const jobNumberMatch = job.job_number?.toString().toLowerCase().includes(term)
    const descriptionMatch = job.description?.toLowerCase().includes(term)
    const nameMatch = job.name?.toLowerCase().includes(term)
    const clientMatch = job.client_name?.toLowerCase().includes(term)

    return jobNumberMatch || descriptionMatch || nameMatch || clientMatch
  })

  return filtered
})

const updateSearchTermFromModelValue = (modelValue: string | number | null) => {
  if (modelValue) {
    const selectedJob = (props.jobs || []).find((job: Job) => job.id === modelValue)
    if (selectedJob) {
      const jobNumber = selectedJob.job_number
      const jobDescription = selectedJob.description || selectedJob.name
      searchTerm.value = `${jobNumber} - ${jobDescription}`
    }
  } else {
    searchTerm.value = ''
  }
}

watch(
  () => props.modelValue,
  (newValue) => {
    updateSearchTermFromModelValue(newValue || null)
  },
  { immediate: true },
)

watch(
  () => props.jobs,
  (newJobs) => {
    if (props.modelValue && (newJobs || []).length > 0) {
      updateSearchTermFromModelValue(props.modelValue)
    }
  },
  { immediate: true },
)

watch(searchTerm, () => {}, { immediate: true })

const onFocus = () => {
  if (props.disabled) return
  updateDropdownPosition()
  showDropdown.value = true
  highlightedIndex.value = -1
}

const onBlur = (event: FocusEvent) => {
  if (props.disabled) return
  setTimeout(() => {
    if (!dropdownRef.value?.contains(event.relatedTarget as Node)) {
      showDropdown.value = false
      highlightedIndex.value = -1
    }
  }, 150)
}

const onInput = () => {
  if (props.disabled) return
  updateDropdownPosition()
  showDropdown.value = true
  highlightedIndex.value = -1

  if (props.modelValue) {
    emit('update:modelValue', null)
    emit('jobSelected', null)
  }
}

const onKeydown = (event: KeyboardEvent) => {
  if (props.disabled || !showDropdown.value || filteredJobs.value.length === 0) return

  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      highlightedIndex.value = Math.min(highlightedIndex.value + 1, filteredJobs.value.length - 1)
      break
    case 'ArrowUp':
      event.preventDefault()
      highlightedIndex.value = Math.max(highlightedIndex.value - 1, -1)
      break
    case 'Enter':
      event.preventDefault()
      if (highlightedIndex.value >= 0) {
        selectJob(filteredJobs.value[highlightedIndex.value])
      }
      break
    case 'Escape':
      event.preventDefault()
      showDropdown.value = false
      highlightedIndex.value = -1
      inputRef.value?.blur()
      break
  }
}

const isStockHoldingJob = (job: Job) => Boolean(job.is_stock_holding)

const selectJob = (job: Job) => {
  if (props.disabled) return

  const jobNumber = job.job_number
  const jobDescription = job.description || job.name
  searchTerm.value = `${jobNumber} - ${jobDescription}`
  showDropdown.value = false
  highlightedIndex.value = -1

  emit('update:modelValue', job.id)
  emit('jobSelected', job)

  inputRef.value?.blur()
}

const handleClickOutside = (event: MouseEvent) => {
  if (
    inputRef.value &&
    !inputRef.value.contains(event.target as Node) &&
    dropdownRef.value &&
    !dropdownRef.value.contains(event.target as Node)
  ) {
    showDropdown.value = false
    highlightedIndex.value = -1
  }
}

onMounted(() => {
  document.addEventListener('click', handleClickOutside)
})

onUnmounted(() => {
  document.removeEventListener('click', handleClickOutside)
})

defineExpose({
  focus: () => inputRef.value?.focus(),
  blur: () => inputRef.value?.blur(),
  clear: () => {
    searchTerm.value = ''
    emit('update:modelValue', null)
    emit('jobSelected', null)
  },
})
</script>
