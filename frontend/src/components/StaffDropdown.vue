<template>
  <div class="relative">
    <label :for="id" class="block text-sm font-medium text-gray-700 mb-1">{{ label }}</label>
    <div class="relative">
      <select
        :id="id"
        v-model="selectedValue"
        :disabled="isLoading"
        class="w-full p-2 border border-gray-200 rounded-md appearance-none bg-white text-gray-900 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:bg-gray-50 disabled:cursor-not-allowed transition-colors"
        @change="handleChange"
      >
        <option v-if="isLoading" value="">Loading staff members...</option>
        <option v-else value="">{{ placeholder }}</option>
        <option v-for="staff in staffOptions" :key="staff.id" :value="staff.id">
          {{ getDisplayName(staff) }}
        </option>
      </select>
      <div v-if="isLoading" class="absolute top-1/2 right-8 transform -translate-y-1/2">
        <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
      </div>
      <div v-else class="absolute top-1/2 right-2 transform -translate-y-1/2 pointer-events-none">
        <ChevronDown class="h-4 w-4 text-gray-400" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch } from 'vue'
import { toast } from 'vue-sonner'
import { ChevronDown } from 'lucide-vue-next'
import { useStaffApi } from '@/composables/useStaffApi'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'

// Use generated types from Zodios API
type KanbanStaff = z.infer<typeof schemas.KanbanStaff>

interface Props {
  id: string
  label: string
  placeholder?: string
  modelValue?: string | number
}

interface Emits {
  (e: 'update:modelValue', value: string | number): void
}

const props = withDefaults(defineProps<Props>(), {
  placeholder: 'Any Staff Member',
})

const emit = defineEmits<Emits>()

const staffOptions = ref<KanbanStaff[]>([])
const selectedValue = ref<string | number>(props.modelValue || '')
const isLoading = ref(false)
const error = ref<string | null>(null)

// Use Zodios API composable
const { listStaffForKanban } = useStaffApi()

const loadStaffOptions = async (): Promise<void> => {
  try {
    isLoading.value = true
    error.value = null
    const data = await listStaffForKanban()
    staffOptions.value = data
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load staff options'
    console.error('Error loading staff options:', err)
    toast.error('Failed to load staff members')
  } finally {
    isLoading.value = false
  }
}

const handleChange = (): void => {
  emit('update:modelValue', selectedValue.value)
}

const getDisplayName = (staff: KanbanStaff): string => {
  // KanbanStaff has display_name which is already constructed
  return staff.display_name || 'Unknown User'
}

watch(
  () => props.modelValue,
  (newValue) => {
    selectedValue.value = newValue || ''
  },
)

onMounted(() => {
  loadStaffOptions()
})
</script>
