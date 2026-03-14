<template>
  <div class="inline-edit-client group">
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
      <div class="relative flex-1">
        <ClientLookup
          id="inline-client-lookup"
          label=""
          v-model="searchQuery"
          :placeholder="placeholder"
          :search-mode="true"
          :edit-mode="true"
          @update:selected-client="handleClientSelected"
          class="min-w-48"
        />
      </div>
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
import { ref, computed, watch } from 'vue'
import { PencilIcon, CheckIcon, XIcon } from 'lucide-vue-next'
import ClientLookup from '../ClientLookup.vue'
import type { Client } from '../../composables/useClientLookup'

interface Props {
  clientName?: string | null
  clientId?: string | null
  placeholder?: string
  displayClass?: string
}

interface Emits {
  'update:client': [client: { id: string; name: string }]
}

const props = withDefaults(defineProps<Props>(), {
  clientName: '',
  clientId: '',
  placeholder: 'Click to select client',
  displayClass: '',
})

const emit = defineEmits<Emits>()

const isEditing = ref(false)
const searchQuery = ref('')
const selectedClient = ref<Client | null>(null)

const displayValue = computed(() => {
  return props.clientName || (isEditing.value ? '' : props.placeholder)
})

const canConfirm = computed(() => {
  return selectedClient.value !== null
})

const startEdit = () => {
  searchQuery.value = props.clientName || ''
  selectedClient.value = null
  isEditing.value = true
}

const handleClientSelected = (client: Client | null) => {
  selectedClient.value = client
  if (client) {
    searchQuery.value = client.name
  }
}

const confirm = () => {
  if (!canConfirm.value || !selectedClient.value) return

  // Only emit if client actually changed
  if (
    selectedClient.value.id !== props.clientId ||
    selectedClient.value.name !== props.clientName
  ) {
    emit('update:client', {
      id: selectedClient.value.id,
      name: selectedClient.value.name,
    })
  }

  isEditing.value = false
}

const cancel = () => {
  searchQuery.value = props.clientName || ''
  selectedClient.value = null
  isEditing.value = false
}

// Watch for external value changes
watch(
  () => props.clientName,
  (newValue) => {
    if (!isEditing.value) {
      searchQuery.value = newValue || ''
    }
  },
)
</script>

<style scoped>
.inline-edit-client :deep(.client-lookup) {
  margin-bottom: 0;
}

.inline-edit-client :deep(.client-lookup label) {
  display: none;
}

/* Hide the blue confirmation element from ClientLookup */
.inline-edit-client :deep(.client-lookup .bg-blue-50) {
  display: none;
}

@media (max-width: 768px) {
  .inline-edit-client .min-w-48 {
    min-width: 12rem;
  }
}
</style>
