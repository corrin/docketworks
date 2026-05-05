<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-5xl mx-auto py-6 px-2 md:px-8 h-full flex flex-col gap-6">
          <div class="flex items-center justify-between mb-2">
            <h1 class="text-2xl font-bold text-indigo-700 flex items-center gap-2">
              <Building2 class="w-7 h-7 text-indigo-400" />
              Company Defaults
            </h1>
          </div>
          <div
            v-if="schemaLoading"
            class="flex flex-col items-center justify-center"
            style="height: 60vh"
          >
            <div class="flex items-center justify-center gap-2">
              <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
              Loading sections…
            </div>
          </div>
          <div v-else class="flex flex-col items-center justify-center" style="height: 60vh">
            <div class="grid grid-cols-2 md:grid-cols-3 gap-4 md:gap-6 w-full max-w-3xl">
              <component
                :is="getSpecialHandler(section.key) === 'ai_providers' ? 'button' : RouterLink"
                v-for="section in orderedSections"
                :key="section.key"
                :to="
                  getSpecialHandler(section.key) === 'ai_providers'
                    ? undefined
                    : `/admin/company/${section.key}`
                "
                class="section-btn"
                :data-automation-id="`AdminCompanyView-${section.key}-button`"
                @click="
                  getSpecialHandler(section.key) === 'ai_providers'
                    ? openAIProvidersDialog()
                    : undefined
                "
              >
                <component :is="section.icon" class="w-12 h-12 mb-2" />
                <span>{{ section.title }}</span>
              </component>
            </div>
          </div>
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
import AppLayout from '../components/AppLayout.vue'
import { ref, onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { Building2 } from 'lucide-vue-next'
import AIProvidersDialog from '../components/AIProvidersDialog.vue'
import type { AIProvider } from '../services/admin-company-defaults-service'
import { useSettingsSchema } from '@/composables/useSettingsSchema'

const {
  orderedSections,
  isLoading: schemaLoading,
  loadSchema,
  getSpecialHandler,
} = useSettingsSchema()

const aiProviders = ref<AIProvider[]>([])
const showAIProvidersDialog = ref(false)

function openAIProvidersDialog() {
  showAIProvidersDialog.value = true
}
function closeAIProvidersDialog() {
  showAIProvidersDialog.value = false
}
function onProvidersUpdate(providers: AIProvider[]) {
  aiProviders.value = providers
}

onMounted(() => {
  loadSchema()
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
  min-width: 140px;
  min-height: 140px;
  border: none;
  outline: none;
  cursor: pointer;
  text-decoration: none;
}

.section-btn:hover,
.section-btn:focus {
  background: linear-gradient(135deg, #c7d2fe 0%, #e0e7ff 100%);
  transform: scale(1.05);
  box-shadow: 0 4px 24px 0 rgba(80, 80, 120, 0.13);
}
</style>
