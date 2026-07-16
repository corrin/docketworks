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
        <option v-if="isLoading" value="">Loading companies...</option>
        <option v-else value="">{{ placeholder }}</option>
        <option v-for="company in companyOptions" :key="company.id" :value="company.id">
          {{ company.name }}
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

type Company = z.infer<typeof schemas.CompanyNameOnly>

interface Props {
  id: string
  label: string
  placeholder?: string
  modelValue?: string
  createdCompany?: Company | null
}

interface Emits {
  (e: 'update:modelValue', value: string): void
  (e: 'selected-company', company: Company | null): void
}

const props = withDefaults(defineProps<Props>(), {
  placeholder: 'Any Company',
  createdCompany: null,
})

const emit = defineEmits<Emits>()

const companyOptions = ref<Company[]>([])
const selectedValue = ref<string>(props.modelValue || '')
const isLoading = ref(false)
const error = ref<string | null>(null)
const selectEl = ref<HTMLSelectElement | null>(null)

const loadCompanyOptions = async (): Promise<void> => {
  try {
    isLoading.value = true
    error.value = null
    const data = await api.companies_all_list()
    companyOptions.value = data
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load company options'
    console.error('Error loading company options:', err)
    toast.error('Failed to load companies')
  } finally {
    isLoading.value = false
  }
}

const handleChange = (): void => {
  emit('update:modelValue', selectedValue.value)
  const company = companyOptions.value.find((c: Company) => c.id === selectedValue.value) || null
  emit('selected-company', company)
}

function upsertCompanyInOptions(c: Company) {
  const idx = companyOptions.value.findIndex((x: Company) => x.id === c.id)
  if (idx === -1) {
    companyOptions.value = [c, ...companyOptions.value]
  } else {
    companyOptions.value[idx] = c
  }
}

async function closeAndSelect(company: Company) {
  upsertCompanyInOptions(company)
  selectedValue.value = company.id
  handleChange()
  await nextTick()
  selectEl.value?.blur()
}

watch(
  () => props.createdCompany,
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
  reload: loadCompanyOptions,
  focus: () => selectEl.value?.focus(),
  blur: () => selectEl.value?.blur(),
})

onMounted(() => {
  loadCompanyOptions()
})
</script>
