<template>
  <div class="relative">
    <label :for="id" class="block text-sm font-medium text-gray-700 mb-1">{{ label }}</label>

    <div class="relative">
      <select
        :id="id"
        ref="selectEl"
        v-model="selectedValue"
        :disabled="isLoading"
        class="w-full p-2 border border-gray-200 rounded-md appearance-none bg-white text-gray-900 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:bg-gray-50 disabled:cursor-not-allowed transition-colors"
        @change="handleChange"
      >
        <option v-if="isLoading" value="">Loading clients...</option>
        <option v-else value="">{{ placeholder }}</option>
        <option v-for="client in clientOptions" :key="client.id" :value="client.id">
          {{ client.name }}
        </option>
      </select>

      <div v-if="isLoading" class="absolute top-1/2 right-8 -translate-y-1/2">
        <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
      </div>
      <div v-else class="absolute top-1/2 right-2 -translate-y-1/2 pointer-events-none">
        <ChevronDown class="h-4 w-4 text-gray-400" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, watch, nextTick } from 'vue'
import { toast } from 'vue-sonner'
import { ChevronDown } from 'lucide-vue-next'
import { schemas } from '@/api/generated/api'
import { api } from '@/api/client'
import { z } from 'zod'

type Client = z.infer<typeof schemas.ClientNameOnly>

interface Props {
  id: string
  label: string
  placeholder?: string
  modelValue?: string
  createdClient?: Client | null
}

interface Emits {
  (e: 'update:modelValue', value: string): void
  (e: 'selected-client', client: Client | null): void
}

const props = withDefaults(defineProps<Props>(), {
  placeholder: 'Any Client',
  createdClient: null,
})

const emit = defineEmits<Emits>()

const clientOptions = ref<Client[]>([])
const selectedValue = ref<string>(props.modelValue || '')
const isLoading = ref(false)
const error = ref<string | null>(null)
const selectEl = ref<HTMLSelectElement | null>(null)

const loadClientOptions = async (): Promise<void> => {
  try {
    isLoading.value = true
    error.value = null
    const data = await api.clients_all_list()
    clientOptions.value = data
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load client options'
    console.error('Error loading client options:', err)
    toast.error('Failed to load clients')
  } finally {
    isLoading.value = false
  }
}

const handleChange = (): void => {
  emit('update:modelValue', selectedValue.value)
  const client = clientOptions.value.find((c: Client) => c.id === selectedValue.value) || null
  emit('selected-client', client)
}

function upsertClientInOptions(c: Client) {
  const idx = clientOptions.value.findIndex((x: Client) => x.id === c.id)
  if (idx === -1) {
    clientOptions.value = [c, ...clientOptions.value]
  } else {
    clientOptions.value[idx] = c
  }
}

async function closeAndSelect(client: Client) {
  upsertClientInOptions(client)
  selectedValue.value = client.id
  handleChange()
  await nextTick()
  selectEl.value?.blur()
}

watch(
  () => props.createdClient,
  (c) => {
    if (!c) return
    closeAndSelect(c)
  },
  { immediate: false },
)

watch(
  () => props.modelValue,
  (newValue) => {
    selectedValue.value = newValue || ''
  },
)

defineExpose({
  reload: loadClientOptions,
  focus: () => selectEl.value?.focus(),
  blur: () => selectEl.value?.blur(),
})

onMounted(() => {
  loadClientOptions()
})
</script>
