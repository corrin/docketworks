<template>
  <div class="inline-edit-text group">
    <div
      v-if="!isEditing"
      @click="startEdit"
      class="cursor-pointer hover:bg-gray-50 rounded px-1 py-1 transition-colors flex items-center"
      :class="displayClass"
    >
      <span>{{ displayValue || placeholder }}</span>
      <PencilIcon class="w-3 h-3 ml-1 opacity-0 group-hover:opacity-100 transition-opacity" />
    </div>

    <div v-else class="flex items-center gap-2">
      <input
        ref="inputRef"
        v-model="editValue"
        @blur="handleBlur"
        @keydown.enter="confirm"
        @keydown.escape="cancel"
        :placeholder="placeholder"
        class="border border-gray-300 rounded px-2 py-1 focus:ring-2 focus:ring-blue-500 focus:border-transparent"
        :class="inputClass"
      />
      <button
        @click="confirm"
        class="p-1 text-green-600 hover:text-green-700 transition-colors"
        :disabled="!canConfirm"
      >
        <CheckIcon class="w-4 h-4" />
      </button>
      <button @click="cancel" class="p-1 text-gray-400 hover:text-gray-600 transition-colors">
        <XIcon class="w-4 h-4" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, watch } from 'vue'
import { PencilIcon, CheckIcon, XIcon } from 'lucide-vue-next'

interface Props {
  value?: string | null
  placeholder?: string
  displayClass?: string
  inputClass?: string
  required?: boolean
  minLength?: number
  maxLength?: number
}

interface Emits {
  'update:value': [value: string]
}

const props = withDefaults(defineProps<Props>(), {
  value: '',
  placeholder: 'Click to edit',
  displayClass: '',
  inputClass: '',
  required: false,
  minLength: 0,
  maxLength: 255,
})

const emit = defineEmits<Emits>()

const isEditing = ref(false)
const editValue = ref('')
const inputRef = ref<HTMLInputElement>()

const displayValue = computed(() => {
  return props.value || (isEditing.value ? '' : props.placeholder)
})

const canConfirm = computed(() => {
  if (props.required && !editValue.value?.trim()) {
    return false
  }
  if (props.minLength && editValue.value.length < props.minLength) {
    return false
  }
  if (props.maxLength && editValue.value.length > props.maxLength) {
    return false
  }
  return true
})

const startEdit = async () => {
  editValue.value = props.value || ''
  isEditing.value = true

  await nextTick()
  inputRef.value?.focus()
  inputRef.value?.select()
}

const confirm = () => {
  if (!canConfirm.value) return

  const newValue = editValue.value.trim()
  // Always emit the value, even if it's the same (to trigger autosave)
  emit('update:value', newValue)

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
.inline-edit-text input {
  min-width: 200px;
}

@media (max-width: 768px) {
  .inline-edit-text input {
    min-width: 150px;
  }
}
</style>
