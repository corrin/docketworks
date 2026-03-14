<template>
  <div data-status-dropdown>
    <label class="block text-sm font-medium text-gray-700 mb-1">{{ label }}</label>
    <div class="relative">
      <button
        type="button"
        @click="toggleDropdown"
        class="w-full px-3 py-2 border border-gray-300 rounded-md bg-white text-left focus:ring-2 focus:ring-blue-500 focus:border-transparent text-sm"
        :class="{ 'ring-2 ring-blue-500': isOpen }"
      >
        <span v-if="selectedStatuses.length === 0" class="text-gray-500"> Select status... </span>
        <span v-else class="text-gray-900">
          {{ displayText }}
        </span>
        <ChevronDown
          class="absolute right-2 top-1/2 transform -translate-y-1/2 h-4 w-4 text-gray-400"
          :class="{ 'rotate-180': isOpen }"
        />
      </button>

      <div
        v-if="isOpen"
        class="absolute z-50 w-full mt-1 bg-white border border-gray-300 rounded-md shadow-lg max-h-60 overflow-y-auto"
      >
        <div class="px-3 py-2 border-b border-gray-100">
          <button
            type="button"
            @click="toggleAll"
            class="text-sm text-blue-600 hover:text-blue-800 font-medium"
          >
            {{
              selectedStatuses.length === JOB_STATUS_CHOICES.length ? 'Deselect All' : 'Select All'
            }}
          </button>
        </div>

        <div
          v-for="status in JOB_STATUS_CHOICES"
          :key="status.key"
          class="px-3 py-2 hover:bg-gray-50 cursor-pointer"
          @click="toggleStatus(status.key)"
        >
          <div class="flex items-center">
            <input
              type="checkbox"
              :checked="selectedStatuses.includes(status.key)"
              class="mr-2 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
              @click.stop
            />
            <span class="text-sm text-gray-900">{{ status.label }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-if="selectedStatuses.length > 0" class="mt-2 flex flex-wrap gap-1">
      <span
        v-for="status in selectedStatuses"
        :key="status"
        class="inline-flex items-center px-2 py-1 rounded text-xs font-medium bg-blue-100 text-blue-800"
      >
        {{ getStatusLabel(status) }}
        <button
          type="button"
          @click="removeStatus(status)"
          class="ml-1 text-blue-600 hover:text-blue-800"
        >
          <X class="w-3 h-3" />
        </button>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { ChevronDown, X } from 'lucide-vue-next'
import { JOB_STATUS_CHOICES } from '../constants/job-status'

interface Props {
  modelValue: string[]
  label?: string
}

const props = withDefaults(defineProps<Props>(), {
  label: 'Status',
})

const emit = defineEmits<{
  'update:modelValue': [value: string[]]
}>()

const isOpen = ref(false)
const selectedStatuses = ref<string[]>([...props.modelValue])

const displayText = computed(() => {
  const count = selectedStatuses.value.length

  switch (true) {
    case count === 0:
      return 'Select status...'
    case count === 1:
      return getStatusLabel(selectedStatuses.value[0])
    case count <= 3:
      return selectedStatuses.value.map(getStatusLabel).join(', ')
    default:
      return `${count} statuses selected`
  }
})

const getStatusLabel = (value: string): string => {
  const option = JOB_STATUS_CHOICES.find((opt) => opt.key === value)
  return option?.label || value
}

const toggleDropdown = () => {
  isOpen.value = !isOpen.value
}

const toggleStatus = (status: string) => {
  if (selectedStatuses.value.includes(status)) {
    removeStatus(status)
    return
  }

  addStatus(status)
}

const addStatus = (status: string) => {
  selectedStatuses.value.push(status)
  emitUpdate()
}

const removeStatus = (status: string) => {
  const index = selectedStatuses.value.indexOf(status)
  if (index > -1) {
    selectedStatuses.value.splice(index, 1)
    emitUpdate()
  }
}

const toggleAll = () => {
  switch (selectedStatuses.value.length === JOB_STATUS_CHOICES.length) {
    case true:
      selectedStatuses.value = []
      break
    case false:
      selectedStatuses.value = JOB_STATUS_CHOICES.map((opt) => opt.key)
      break
  }

  emitUpdate()
}

const emitUpdate = () => {
  emit('update:modelValue', [...selectedStatuses.value])
}

const handleOutsideClick = (event: Event) => {
  const target = event.target as HTMLElement
  const dropdown = target.closest('[data-status-dropdown]')

  if (!dropdown) {
    isOpen.value = false
  }
}

onMounted(() => {
  document.addEventListener('click', handleOutsideClick)
})

onUnmounted(() => {
  document.removeEventListener('click', handleOutsideClick)
})

import { watch } from 'vue'

watch(
  () => props.modelValue,
  (newValue) => {
    selectedStatuses.value = [...newValue]
  },
)
</script>

<style scoped>
.dropdown-enter-active,
.dropdown-leave-active {
  transition: all 0.2s ease;
}

.dropdown-enter-from,
.dropdown-leave-to {
  opacity: 0;
  transform: translateY(-10px);
}
</style>
