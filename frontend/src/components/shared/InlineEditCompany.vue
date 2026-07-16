<template>
  <div class="inline-edit-company group">
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
        <CompanyLookup
          id="inline-company-lookup"
          label=""
          v-model="searchQuery"
          :placeholder="placeholder"
          :search-mode="true"
          :edit-mode="true"
          @update:selected-company="handleCompanySelected"
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
import CompanyLookup from '../CompanyLookup.vue'
import type { Company } from '../../composables/useCompanyLookup'

interface Props {
  companyName?: string | null
  companyId?: string | null
  placeholder?: string
  displayClass?: string
}

interface Emits {
  'update:company': [company: { id: string; name: string }]
}

const props = withDefaults(defineProps<Props>(), {
  companyName: '',
  companyId: '',
  placeholder: 'Click to select company',
  displayClass: '',
})

const emit = defineEmits<Emits>()

const isEditing = ref(false)
const searchQuery = ref('')
const selectedCompany = ref<Company | null>(null)

const displayValue = computed(() => {
  return props.companyName || (isEditing.value ? '' : props.placeholder)
})

const canConfirm = computed(() => {
  return selectedCompany.value !== null
})

const startEdit = () => {
  searchQuery.value = props.companyName || ''
  selectedCompany.value = null
  isEditing.value = true
}

const handleCompanySelected = (company: Company | null) => {
  selectedCompany.value = company
  if (company) {
    searchQuery.value = company.name
  }
}

const confirm = () => {
  if (!canConfirm.value || !selectedCompany.value) return

  // Only emit if company actually changed
  if (
    selectedCompany.value.id !== props.companyId ||
    selectedCompany.value.name !== props.companyName
  ) {
    emit('update:company', {
      id: selectedCompany.value.id,
      name: selectedCompany.value.name,
    })
  }

  isEditing.value = false
}

const cancel = () => {
  searchQuery.value = props.companyName || ''
  selectedCompany.value = null
  isEditing.value = false
}

// Watch for external value changes
watch(
  () => props.companyName,
  (newValue) => {
    if (!isEditing.value) {
      searchQuery.value = newValue || ''
    }
  },
)
</script>

<style scoped>
.inline-edit-company :deep(.company-lookup) {
  margin-bottom: 0;
}

.inline-edit-company :deep(.company-lookup label) {
  display: none;
}

/* Hide the blue confirmation element from CompanyLookup */
.inline-edit-company :deep(.company-lookup .bg-blue-50) {
  display: none;
}

@media (max-width: 768px) {
  .inline-edit-company .min-w-48 {
    min-width: 12rem;
  }
}
</style>
