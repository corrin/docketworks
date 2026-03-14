<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-5xl mx-auto py-6 px-2 md:px-8 h-full flex flex-col gap-6">
          <div class="flex items-center justify-between mb-2">
            <h1 class="text-2xl font-bold text-indigo-700 flex items-center gap-2">
              <Building2 class="w-7 h-7 text-indigo-400 animate-pulse" />
              Company Defaults
            </h1>
          </div>
          <div
            v-if="loading || schemaLoading"
            class="flex flex-col items-center justify-center"
            style="height: 60vh"
          >
            <div class="flex items-center justify-center gap-2">
              <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
              Company defaults are still loading, please wait
            </div>
          </div>
          <div v-else class="flex flex-col items-center justify-center" style="height: 60vh">
            <div class="grid grid-cols-3 gap-6 w-full max-w-3xl">
              <button
                v-for="section in orderedSections"
                :key="section.key"
                class="section-btn"
                :data-automation-id="`AdminCompanyView-${section.key}-button`"
                @click="openSection(section.key)"
              >
                <component :is="section.icon" class="w-12 h-12 mb-2" />
                <span>{{ section.title }}</span>
              </button>
            </div>
          </div>
          <div class="flex justify-center mt-8">
            <Button
              type="button"
              variant="default"
              class="bg-green-600 hover:bg-green-700 text-white px-8 py-3 flex items-center gap-2 text-base font-semibold rounded shadow"
              data-automation-id="AdminCompanyView-save-all-button"
              @click="saveAll"
            >
              <Save class="w-5 h-5" /> Save All
            </Button>
          </div>
          <SectionModal
            v-if="modalSection"
            :section="modalSection"
            :form="form"
            @close="closeSection"
            @update="onSectionUpdate"
          />
        </div>
      </div>
      <AIProvidersDialog
        v-if="showAIProvidersDialog"
        :providers="aiProviders"
        @close="closeAIProvidersDialog"
        @update:providers="onProvidersUpdate"
      />
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { debugLog } from '../utils/debug'

import AppLayout from '../components/AppLayout.vue'
import { Button } from '../components/ui/button'
import { ref, onMounted } from 'vue'
import type { AIProvider } from '../services/admin-company-defaults-service'
import { Building2, Save } from 'lucide-vue-next'
import AIProvidersDialog from '../components/AIProvidersDialog.vue'
import SectionModal from '../components/SectionModal.vue'
import {
  getCompanyDefaults,
  updateCompanyDefaults,
} from '../services/admin-company-defaults-service'
import type {
  CompanyDefaults,
  PatchedCompanyDefaults,
} from '../services/admin-company-defaults-service'
import { toast } from 'vue-sonner'
import { useSettingsSchema } from '@/composables/useSettingsSchema'

const {
  orderedSections,
  sections,
  isLoading: schemaLoading,
  loadSchema,
  getSpecialHandler,
} = useSettingsSchema()

const companyDefaults = ref<CompanyDefaults>({} as CompanyDefaults)
const form = ref<CompanyDefaults>({} as CompanyDefaults)
const aiProviders = ref<AIProvider[]>([])
const loading = ref(true)
const showAIProvidersDialog = ref(false)
const modalSection = ref<string | null>(null)

debugLog('[AdminCompanyView] companyDefaults:', companyDefaults.value)
debugLog('[AdminCompanyView] form:', form.value)

function openAIProvidersDialog() {
  debugLog('[AdminCompanyView] openAIProvidersDialog, providers:', aiProviders.value)
  showAIProvidersDialog.value = true
}
function closeAIProvidersDialog() {
  showAIProvidersDialog.value = false
}
async function fetchDefaults() {
  loading.value = true
  const data = await getCompanyDefaults()
  debugLog('[AdminCompanyView] getCompanyDefaults() result:', data)
  companyDefaults.value = data
  form.value = JSON.parse(JSON.stringify(data))
  // AI providers are managed separately via AIProvidersDialog
  debugLog('[AdminCompanyView] form after fetch:', form.value)
  loading.value = false
}
async function saveAll() {
  loading.value = true
  try {
    debugLog('[AdminCompanyView] saveAll() called with form.value:', form.value)
    debugLog('[AdminCompanyView] saveAll() AI providers specifically:', aiProviders.value)

    // Build payload dynamically from schema - only include writable fields
    const payload: Partial<PatchedCompanyDefaults> = {}

    // Get all writable field keys from schema
    for (const section of sections.value) {
      for (const field of section.fields) {
        if (!field.readOnly) {
          const key = field.key as keyof CompanyDefaults
          if (key in form.value) {
            ;(payload as Record<string, unknown>)[key] = form.value[key]
          }
        }
      }
    }

    debugLog('[AdminCompanyView] saveAll() dynamic payload:', payload)

    await updateCompanyDefaults(payload)
    toast.success('Company defaults saved successfully!')
    await fetchDefaults()
  } catch (error) {
    debugLog('[AdminCompanyView] saveAll() error:', error)
    toast.error('Failed to save company defaults.')
  }
  loading.value = false
}
function onProvidersUpdate(providers: AIProvider[]) {
  debugLog('[AdminCompanyView] onProvidersUpdate called with:', providers)
  debugLog(
    '[AdminCompanyView] onProvidersUpdate, new providers:',
    providers.map((p) => ({
      name: p.name,
      default: p.default,
      id: p.id,
    })),
  )

  aiProviders.value = providers
  debugLog('[AdminCompanyView] aiProviders updated to:', aiProviders.value)
}
function openSection(sectionKey: string) {
  const handler = getSpecialHandler(sectionKey)

  if (handler === 'ai_providers') {
    openAIProvidersDialog()
    return
  }

  modalSection.value = sectionKey
}
function closeSection() {
  modalSection.value = null
}
function onSectionUpdate(newData: Partial<CompanyDefaults>) {
  Object.assign(form.value, newData)
}
onMounted(async () => {
  await Promise.all([loadSchema(), fetchDefaults()])
})
</script>

<style scoped>
.section-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.8);
  border-radius: 0.75rem;
  box-shadow: 0 2px 12px 0 rgba(80, 80, 120, 0.08);
  padding: 1.5rem;
  color: #3730a3;
  font-weight: 600;
  font-size: 1.125rem;
  transition:
    background 0.2s,
    transform 0.2s;
  min-width: 160px;
  min-height: 140px;
  border: none;
  outline: none;
  cursor: pointer;
}

.section-btn:hover,
.section-btn:focus {
  background: linear-gradient(135deg, #c7d2fe 0%, #e0e7ff 100%);
  transform: scale(1.05);
  box-shadow: 0 4px 24px 0 rgba(80, 80, 120, 0.13);
}
</style>
