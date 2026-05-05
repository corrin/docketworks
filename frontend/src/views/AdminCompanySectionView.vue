<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto">
        <div class="max-w-5xl mx-auto py-6 px-4 md:px-8 flex flex-col gap-10">
          <h1 class="text-2xl font-bold text-indigo-700 flex items-center gap-3 flex-wrap">
            <RouterLink
              to="/admin/company"
              class="flex items-center gap-2 hover:underline"
              data-automation-id="AdminCompanySectionView-back-button"
            >
              <ArrowLeft class="w-6 h-6" />
              Company Defaults
            </RouterLink>
            <ChevronRight class="w-6 h-6 text-gray-400" />
            <span class="flex items-center gap-2">
              <component :is="sectionIcon" class="w-7 h-7 text-indigo-400" />
              {{ sectionTitle }}
            </span>
          </h1>

          <div v-if="loading || schemaLoading" class="flex items-center justify-center gap-2 py-16">
            <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
            Loading…
          </div>

          <div v-else-if="!sectionExists" class="py-16 text-center text-gray-500">
            Unknown section: <code>{{ section }}</code
            >. <RouterLink to="/admin/company" class="text-indigo-600 underline">Back</RouterLink>
          </div>

          <SectionForm
            v-else
            v-model="form"
            :section="section"
            data-automation-id="AdminCompanySectionView-form"
          />
        </div>
      </div>

      <div
        v-if="!loading && !schemaLoading && sectionExists"
        class="border-t bg-white/95 backdrop-blur supports-[backdrop-filter]:bg-white/75 px-4 md:px-8 py-3 flex justify-end gap-2 sticky bottom-0"
      >
        <Button
          variant="outline"
          :disabled="saving"
          data-automation-id="AdminCompanySectionView-cancel-button"
          @click="goBack"
        >
          Cancel
        </Button>
        <Button
          variant="default"
          class="bg-green-600 hover:bg-green-700 text-white flex items-center gap-2"
          :disabled="saving || !isDirty"
          data-automation-id="AdminCompanySectionView-save-button"
          @click="save"
        >
          <Save class="w-4 h-4" />
          {{ saving ? 'Saving…' : 'Save' }}
        </Button>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { onBeforeRouteLeave, useRouter, RouterLink } from 'vue-router'
import { ArrowLeft, ChevronRight, Save, HelpCircle } from 'lucide-vue-next'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import SectionForm from '@/components/SectionForm.vue'
import { useSettingsSchema } from '@/composables/useSettingsSchema'
import {
  getCompanyDefaults,
  updateCompanyDefaults,
} from '@/services/admin-company-defaults-service'
import type {
  CompanyDefaults,
  PatchedCompanyDefaults,
} from '@/services/admin-company-defaults-service'
import { toast } from 'vue-sonner'

const props = defineProps<{ section: string }>()
const router = useRouter()

const {
  isLoading: schemaLoading,
  loadSchema,
  getSectionByKey,
  getFieldsForSection,
} = useSettingsSchema()

const companyDefaults = ref<CompanyDefaults>({} as CompanyDefaults)
const form = ref<Record<string, unknown>>({})
const loading = ref(true)
const saving = ref(false)

const currentSection = computed(() => getSectionByKey(props.section))
const sectionExists = computed(() => !!currentSection.value)
const sectionTitle = computed(() => currentSection.value?.title ?? props.section)
const sectionIcon = computed(() => currentSection.value?.icon ?? HelpCircle)

const isDirty = computed(() => {
  const fields = getFieldsForSection(props.section)
  for (const field of fields) {
    if (field.readOnly) continue
    const a = (form.value as Record<string, unknown>)[field.key]
    const b = (companyDefaults.value as unknown as Record<string, unknown>)[field.key]
    if (JSON.stringify(a) !== JSON.stringify(b)) return true
  }
  return false
})

async function loadDefaults() {
  loading.value = true
  try {
    const data = await getCompanyDefaults()
    companyDefaults.value = data
    form.value = JSON.parse(JSON.stringify(data))
  } finally {
    loading.value = false
  }
}

async function save() {
  if (saving.value) return
  saving.value = true
  try {
    const fields = getFieldsForSection(props.section)
    const payload: Partial<PatchedCompanyDefaults> = {}
    for (const field of fields) {
      if (field.readOnly) continue
      if (field.type === 'image') continue // handled by upload endpoint, not partial_update
      const key = field.key
      if (key in form.value) {
        ;(payload as Record<string, unknown>)[key] = form.value[key]
      }
    }
    await updateCompanyDefaults(payload)
    toast.success(`${sectionTitle.value} saved`)
    // Refresh snapshot so isDirty resets without losing the user's view.
    await loadDefaults()
  } catch (error) {
    console.error('[AdminCompanySectionView] save() error:', error)
    toast.error(`Failed to save ${sectionTitle.value}`)
  } finally {
    saving.value = false
  }
}

function goBack() {
  router.push('/admin/company')
}

onBeforeRouteLeave((_to, _from, next) => {
  if (!isDirty.value) return next()
  const confirmed = window.confirm('You have unsaved changes. Discard them and leave this page?')
  next(confirmed)
})

watch(
  () => props.section,
  () => {
    // Re-snapshot the form when the user navigates between section sub-pages
    // without unmounting (shouldn't happen with current routes, but cheap).
    form.value = JSON.parse(JSON.stringify(companyDefaults.value))
  },
)

onMounted(async () => {
  await Promise.all([loadSchema(), loadDefaults()])
})
</script>
