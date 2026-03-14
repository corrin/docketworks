<template>
  <div class="inline-edit-select group" :data-automation-id="automationId || undefined">
    <div
      v-if="!isEditing"
      @click="startEdit"
      class="cursor-pointer hover:bg-gray-50 rounded px-1 py-1 transition-colors flex items-center"
      :class="displayClass"
      :data-automation-id="automationId ? `${automationId}-display` : undefined"
    >
      <span>{{ displayValue || placeholder }}</span>
      <PencilIcon class="w-3 h-3 ml-1 opacity-0 group-hover:opacity-100 transition-opacity" />
    </div>

    <div v-else class="flex items-center gap-2">
      <select
        ref="selectRef"
        v-model="editValue"
        @blur="handleBlur"
        @keydown.enter="confirm"
        @keydown.escape="cancel"
        class="border border-gray-300 rounded px-2 py-1 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        :class="selectClass"
        :data-automation-id="automationId ? `${automationId}-select` : undefined"
      >
        <option v-for="option in options" :key="option.key" :value="option.key">
          {{ option.label }}
        </option>
      </select>
      <button
        @click="confirm"
        class="p-1 text-green-600 hover:text-green-700 transition-colors"
        :disabled="!canConfirm"
        :data-automation-id="automationId ? `${automationId}-confirm` : undefined"
      >
        <CheckIcon class="w-4 h-4" />
      </button>
      <button
        @click="cancel"
        class="p-1 text-gray-400 hover:text-gray-600 transition-colors"
        :data-automation-id="automationId ? `${automationId}-cancel` : undefined"
      >
        <XIcon class="w-4 h-4" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import { PencilIcon, CheckIcon, XIcon } from 'lucide-vue-next'

interface SelectOption {
  key: string
  label: string
  tooltip?: string
}

interface Props {
  value?: string | null
  options: SelectOption[]
  placeholder?: string
  displayClass?: string
  selectClass?: string
  required?: boolean
  automationId?: string
}

interface Emits {
  'update:value': [value: string]
}

const props = withDefaults(defineProps<Props>(), {
  value: '',
  placeholder: 'Select option',
  displayClass: '',
  selectClass: '',
  required: false,
  automationId: '',
})

const emit = defineEmits<Emits>()

const isEditing = ref(false)
const editValue = ref('')
const selectRef = ref<HTMLSelectElement>()

const displayValue = computed(() => {
  if (!props.value) return props.placeholder
  const option = props.options.find((opt) => opt.key === props.value)
  return option?.label || props.value
})

const canConfirm = computed(() => {
  if (props.required && !editValue.value) {
    return false
  }
  return true // Allow confirmation even if value hasn't changed
})

const startEdit = async () => {
  editValue.value = props.value || ''
  isEditing.value = true

  await nextTick()
  selectRef.value?.focus()
}

const confirm = () => {
  if (!canConfirm.value) return

  // Always emit the value to trigger autosave
  emit('update:value', editValue.value)

  isEditing.value = false
}

const cancel = () => {
  editValue.value = props.value || ''
  isEditing.value = false
}

const handleBlur = () => {
  // Delay to allow click on confirm/cancel buttons
  setTimeout(() => {
    if (isEditing.value) {
      confirm()
    }
  }, 150)
}

// Watch for external value changes
watch(
  () => props.value,
  (newValue) => {
    if (!isEditing.value) {
      editValue.value = newValue || ''
    }
  },
)
</script>

<style scoped>
.inline-edit-select select {
  min-width: 150px;
}

@media (max-width: 768px) {
  .inline-edit-select select {
    min-width: 120px;
  }
}
</style>
