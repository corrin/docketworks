<template>
  <div class="relative">
    <input
      ref="inputRef"
      :value="modelValue"
      type="text"
      :placeholder="placeholder"
      autocomplete="off"
      data-1p-ignore
      data-lpignore="true"
      data-form-type="other"
      class="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-colors"
      :class="{ 'border-blue-500': showSuggestions && suggestions.length > 0 }"
      @input="handleInput"
      @focus="handleFocus"
      @blur="handleBlur"
      @keydown="handleKeydown"
      data-automation-id="AddressAutocompleteInput"
    />

    <!-- Loading indicator -->
    <div v-if="isLoading" class="absolute right-3 top-1/2 -translate-y-1/2 pointer-events-none">
      <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-600"></div>
    </div>

    <!-- Suggestions dropdown -->
    <div
      v-if="showSuggestions && suggestions.length > 0"
      class="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-md shadow-lg max-h-60 overflow-y-auto"
      data-automation-id="AddressAutocompleteInput-suggestions"
    >
      <div
        v-for="(suggestion, index) in suggestions"
        :key="suggestion.google_place_id || index"
        class="px-3 py-2 text-sm cursor-pointer transition-colors"
        :class="{
          'bg-blue-50 text-blue-900': index === highlightedIndex,
          'hover:bg-gray-50': index !== highlightedIndex,
        }"
        @mousedown.prevent="selectSuggestion(suggestion)"
        @mouseenter="highlightedIndex = index"
      >
        <div class="font-medium text-gray-900">{{ formatAddress(suggestion) }}</div>
        <div v-if="suggestion.city || suggestion.state" class="text-xs text-gray-500">
          {{ formatSubtext(suggestion) }}
        </div>
      </div>
    </div>

    <!-- No results message -->
    <div
      v-if="showSuggestions && !isLoading && suggestions.length === 0 && modelValue.length >= 3"
      class="absolute z-50 w-full mt-1 bg-white border border-gray-200 rounded-md shadow-lg"
    >
      <div class="px-3 py-2 text-sm text-gray-500">
        No matching addresses found. You can enter the address manually.
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, onMounted } from 'vue'
import { api } from '@/api/client'
import { debugLog } from '@/utils/debug'
import type { AddressCandidate } from '@/composables/usePickupAddressManagement'

const props = withDefaults(
  defineProps<{
    modelValue: string
    placeholder?: string
    debounceMs?: number
    autofocus?: boolean
  }>(),
  {
    placeholder: 'Start typing address...',
    debounceMs: 300,
    autofocus: false,
  },
)

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'select-candidate': [candidate: AddressCandidate]
}>()

const inputRef = ref<HTMLInputElement | null>(null)
const suggestions = ref<AddressCandidate[]>([])
const isLoading = ref(false)
const showSuggestions = ref(false)
const highlightedIndex = ref(-1)

let currentRequestId = 0

let debounceTimer: number | undefined

onMounted(() => {
  if (props.autofocus && inputRef.value) {
    inputRef.value.focus()
  }
})

const handleInput = (event: Event) => {
  const target = event.target as HTMLInputElement
  const value = target.value
  emit('update:modelValue', value)

  // Reset highlighted index when typing
  highlightedIndex.value = -1

  // Debounce the API call
  clearTimeout(debounceTimer)

  if (value.length < 3) {
    suggestions.value = []
    return
  }

  debounceTimer = window.setTimeout(() => {
    searchAddress(value)
  }, props.debounceMs)
}

const searchAddress = async (query: string) => {
  if (query.length < 3) {
    suggestions.value = []
    return
  }

  const requestId = ++currentRequestId
  isLoading.value = true
  try {
    const response = await api.clients_addresses_validate_create({
      address: query,
    })
    if (requestId !== currentRequestId) {
      return
    }
    suggestions.value = response.candidates || []
    // Show suggestions dropdown when results arrive (fixes race with blur events)
    if (suggestions.value.length > 0) {
      showSuggestions.value = true
    }
    debugLog('Address suggestions:', suggestions.value)
  } catch (error) {
    if (requestId === currentRequestId) {
      debugLog('Error fetching address suggestions:', error)
      suggestions.value = []
    }
  } finally {
    if (requestId === currentRequestId) {
      isLoading.value = false
    }
  }
}

const selectSuggestion = (suggestion: AddressCandidate) => {
  // Update the input with the formatted address
  emit('update:modelValue', suggestion.street || suggestion.formatted_address || '')
  // Emit the full candidate for parent to use
  emit('select-candidate', suggestion)
  // Close suggestions
  showSuggestions.value = false
  suggestions.value = []
}

const handleFocus = () => {
  showSuggestions.value = true
  if (props.modelValue.length >= 3 && suggestions.value.length === 0) {
    searchAddress(props.modelValue)
  }
}

const handleBlur = () => {
  // Delay closing to allow click on suggestion
  setTimeout(() => {
    showSuggestions.value = false
  }, 200)
}

const handleKeydown = (event: KeyboardEvent) => {
  if (!showSuggestions.value || suggestions.value.length === 0) {
    return
  }

  switch (event.key) {
    case 'ArrowDown':
      event.preventDefault()
      highlightedIndex.value = Math.min(highlightedIndex.value + 1, suggestions.value.length - 1)
      break
    case 'ArrowUp':
      event.preventDefault()
      highlightedIndex.value = Math.max(highlightedIndex.value - 1, 0)
      break
    case 'Enter':
      event.preventDefault()
      if (highlightedIndex.value >= 0 && highlightedIndex.value < suggestions.value.length) {
        selectSuggestion(suggestions.value[highlightedIndex.value])
      }
      break
    case 'Escape':
      showSuggestions.value = false
      highlightedIndex.value = -1
      break
  }
}

const formatAddress = (suggestion: AddressCandidate) => {
  // Strip ", New Zealand" from the end of formatted addresses
  const addr = suggestion.formatted_address || ''
  return addr.replace(/, New Zealand$/i, '')
}

const formatSubtext = (suggestion: AddressCandidate) => {
  const parts = []
  if (suggestion.city) parts.push(suggestion.city)
  if (suggestion.state) parts.push(suggestion.state)
  return parts.join(', ')
}

// Clear suggestions when modelValue is cleared externally
watch(
  () => props.modelValue,
  (value) => {
    if (!value) {
      suggestions.value = []
    }
  },
)
</script>

<style scoped>
.animate-spin {
  animation: spin 1s linear infinite;
}

@keyframes spin {
  from {
    transform: rotate(0deg);
  }
  to {
    transform: rotate(360deg);
  }
}
</style>
