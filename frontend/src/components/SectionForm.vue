<template>
  <div class="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-4">
    <template v-for="field in genericFieldsForRender" :key="field.key">
      <label
        class="flex flex-col gap-1 text-sm font-medium"
        :class="FIELD_COL_SPAN_OVERRIDES[field.key] === 2 ? 'md:col-span-2' : ''"
      >
        <span class="flex items-center gap-2 text-gray-700">
          <component :is="field.icon" class="w-4 h-4 text-indigo-400" />
          {{ field.label }}
        </span>

        <Checkbox
          v-if="field.type === 'boolean'"
          v-model="localForm[field.key] as boolean | null | undefined"
          :data-automation-id="`SectionForm-${section}-field-${field.key}`"
        />

        <div v-else-if="field.type === 'date'" class="relative">
          <Input
            :modelValue="formatDateTime(localForm[field.key] as string | Date | null)"
            type="text"
            class="h-9 text-sm cursor-pointer bg-white"
            readonly
            @focus="openCalendar(field.key)"
            @click="openCalendar(field.key)"
          />
          <transition name="fade">
            <div
              v-if="calendarField === field.key"
              class="absolute z-50 left-0 bottom-12 w-max min-w-[260px] bg-white border border-gray-200 rounded-lg shadow-lg p-4"
              @click.stop
            >
              <Calendar
                :modelValue="
                  (getValidDate(localForm[field.key] as string | Date | null) ||
                    getValidDate(modelValue[field.key] as string | Date | null)) as any
                "
                @update:modelValue="
                  (date) => onCalendarSelect(field.key, date as CalendarDateTime | null)
                "
              />
              <div class="flex justify-end mt-2">
                <Button size="sm" variant="outline" @click="closeCalendar">Close</Button>
              </div>
            </div>
          </transition>
        </div>

        <div v-else-if="field.type === 'image'" class="flex flex-col gap-2">
          <div class="flex items-center gap-3 flex-wrap">
            <img
              v-if="localForm[field.key + '_url']"
              :src="localForm[field.key + '_url'] as string"
              :alt="field.label"
              class="h-14 w-auto rounded border border-gray-200 object-contain bg-white"
            />
            <span v-else class="text-xs text-gray-400 italic">No image</span>
            <label
              class="cursor-pointer inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded border border-indigo-300 text-indigo-600 hover:bg-indigo-50 transition"
            >
              <Upload class="w-3.5 h-3.5" />
              Upload
              <input
                type="file"
                accept="image/*"
                class="hidden"
                @change="(e) => onLogoUpload(field.key, e)"
              />
            </label>
            <button
              v-if="localForm[field.key + '_url']"
              type="button"
              class="inline-flex items-center gap-1 px-2 py-1 text-xs font-medium rounded border border-red-300 text-red-600 hover:bg-red-50 transition"
              @click="onLogoDelete(field.key)"
            >
              <Trash2 class="w-3.5 h-3.5" />
              Remove
            </button>
          </div>
          <p v-if="logoGuidance(field.key)" class="text-xs text-gray-500">
            {{ logoGuidance(field.key) }}
          </p>
          <p v-if="logoErrors[field.key]" class="text-red-600 text-xs">
            {{ logoErrors[field.key] }}
          </p>
        </div>

        <select
          v-else-if="field.type === 'client'"
          v-model="localForm[field.key] as string"
          class="h-9 text-sm rounded-md border border-input bg-background px-3 py-1"
          :class="{ 'bg-gray-100 cursor-not-allowed': field.readOnly }"
          :data-automation-id="`SectionForm-${section}-field-${field.key}`"
          :disabled="field.readOnly || clientOptionsLoading"
        >
          <option v-for="client in clientOptions" :key="client.id" :value="client.id">
            {{ client.name }}
          </option>
        </select>

        <Textarea
          v-else-if="field.type === 'textarea'"
          v-model="localForm[field.key] as string | undefined"
          class="min-h-24 text-sm"
          :class="{ 'bg-gray-100 cursor-not-allowed': field.readOnly }"
          :data-automation-id="`SectionForm-${section}-field-${field.key}`"
          :readonly="field.readOnly"
        />

        <Input
          v-else
          v-model="localForm[field.key] as string | number | undefined"
          :type="inputType(field.type)"
          class="h-9 text-sm"
          :class="{ 'bg-gray-100 cursor-not-allowed': field.readOnly }"
          :data-automation-id="`SectionForm-${section}-field-${field.key}`"
          :readonly="field.readOnly"
          :step="
            field.key === 'time_markup' || field.key === 'materials_markup' ? 'any' : undefined
          "
          :min="field.key === 'time_markup' || field.key === 'materials_markup' ? 0 : undefined"
          :max="field.key === 'time_markup' || field.key === 'materials_markup' ? 1 : undefined"
        />

        <p v-if="field.help_text" class="text-xs text-gray-500">{{ field.help_text }}</p>
      </label>
    </template>

    <div v-if="isWorkingHours" class="md:col-span-2 flex flex-col gap-3">
      <div
        v-for="day in workingDays"
        :key="day.key"
        class="flex flex-col sm:flex-row sm:items-center gap-2 sm:gap-4 rounded-md border border-gray-200 p-3"
      >
        <span class="sm:w-28 font-medium text-sm flex items-center gap-2">
          <Clock class="w-4 h-4 text-indigo-400" />
          {{ day.label }}
        </span>
        <div class="flex gap-2 flex-1">
          <label class="flex-1 flex flex-col gap-1">
            <span class="text-xs text-gray-500">Start</span>
            <Input
              v-model="localForm[day.startKey] as string"
              type="text"
              class="h-9 text-sm"
              placeholder="08:00"
              :data-automation-id="`SectionForm-${section}-field-${day.startKey}`"
            />
          </label>
          <label class="flex-1 flex flex-col gap-1">
            <span class="text-xs text-gray-500">End</span>
            <Input
              v-model="localForm[day.endKey] as string"
              type="text"
              class="h-9 text-sm"
              placeholder="17:00"
              :data-automation-id="`SectionForm-${section}-field-${day.endKey}`"
            />
          </label>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import Button from '@/components/ui/button/Button.vue'
import Input from '@/components/ui/input/Input.vue'
import Textarea from '@/components/ui/textarea/Textarea.vue'
import Checkbox from '@/components/ui/checkbox/Checkbox.vue'
import Calendar from '@/components/ui/calendar/Calendar.vue'
import { Clock, Upload, Trash2 } from 'lucide-vue-next'
import { ref, computed, watch } from 'vue'
import { z } from 'zod'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { CalendarDateTime, parseDateTime } from '@internationalized/date'
import {
  useSettingsSchema,
  REMOVED_SETTING_KEYS,
  omitRemovedSettings,
} from '@/composables/useSettingsSchema'
import { uploadLogo, deleteLogo } from '@/services/admin-company-defaults-service'
import { toast } from 'vue-sonner'

type ClientOption = z.infer<typeof schemas.ClientNameOnly>

const props = defineProps<{ section: string; modelValue: Record<string, unknown> }>()
const emit = defineEmits<{ (e: 'update:modelValue', value: Record<string, unknown>): void }>()

const { getFieldsForSection, getSpecialHandler } = useSettingsSchema()
const localForm = ref(props.modelValue)

// Layout overrides — purely a frontend concern. The backend says *what* a
// setting is (label, type, section, help_text); this dict says *how* the
// form lays it out on a 2-column grid. Default is 1; entries here only
// exist for fields whose values are typically long enough to deserve
// the full row width (addresses, URLs, long IDs). A new field added to
// CompanyDefaults without an entry here renders at the default width
// — visible but compact, which is the right failure mode.
const FIELD_COL_SPAN_OVERRIDES: Record<string, 2> = {
  address_line1: 2,
  address_line2: 2,
  company_url: 2,
  master_quote_template_url: 2,
  master_quote_template_id: 2,
  gdrive_quotes_folder_url: 2,
  gdrive_quotes_folder_id: 2,
  google_shared_drive_id: 2,
  gdrive_how_we_work_folder_id: 2,
  gdrive_sops_folder_id: 2,
  gdrive_reference_library_folder_id: 2,
  xero_tenant_id: 2,
  xero_payroll_calendar_id: 2,
}

const logoErrors = ref<Record<string, string>>({})
const clientOptions = ref<ClientOption[]>([])
const clientOptionsLoading = ref(false)

const LOGO_ASPECT_RULES: Record<
  string,
  { min: number; max: number; label: string; expected: string; hint: string }
> = {
  logo: {
    min: 0.85,
    max: 1.18,
    label: 'square logo',
    expected: 'approximately 1:1 (square)',
    hint: 'Please upload a square image.',
  },
  logo_wide: {
    min: 2.5,
    max: 8.0,
    label: 'wide letterhead logo',
    expected: 'between 2.5:1 and 8:1 (wide)',
    hint: 'Please upload a wide letterhead-style image (around 4× wider than tall).',
  },
}

const LOGO_GUIDANCE: Record<string, string> = {
  logo: 'Square image, roughly 1:1. Used as a compact mark.',
  logo_wide: 'Wide letterhead image, roughly 3:1 to 6:1. Used at the top of PDFs.',
}

function logoGuidance(fieldKey: string): string {
  return LOGO_GUIDANCE[fieldKey] ?? ''
}

function readImageDimensions(file: File): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      const dims = { width: img.naturalWidth, height: img.naturalHeight }
      URL.revokeObjectURL(url)
      resolve(dims)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('Could not read image file'))
    }
    img.src = url
  })
}

async function onLogoUpload(fieldKey: string, event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return

  const rule = LOGO_ASPECT_RULES[fieldKey]
  if (rule) {
    let dims: { width: number; height: number }
    try {
      dims = await readImageDimensions(file)
    } catch (e) {
      console.error('Could not read image dimensions:', e)
      logoErrors.value = {
        ...logoErrors.value,
        [fieldKey]: 'Could not read image file. Please try a different image.',
      }
      input.value = ''
      return
    }
    if (dims.height === 0) {
      logoErrors.value = {
        ...logoErrors.value,
        [fieldKey]: 'Image has invalid dimensions.',
      }
      input.value = ''
      return
    }
    const ratio = dims.width / dims.height
    if (ratio < rule.min || ratio > rule.max) {
      const ratioStr = ratio.toFixed(2)
      logoErrors.value = {
        ...logoErrors.value,
        [fieldKey]:
          `This image is ${ratioStr}:1 (width:height). ` +
          `Expected ${rule.expected} for the ${rule.label} field. ` +
          rule.hint,
      }
      input.value = ''
      return
    }
    if (logoErrors.value[fieldKey]) {
      const next = { ...logoErrors.value }
      delete next[fieldKey]
      logoErrors.value = next
    }
  }

  try {
    const updated = await uploadLogo(fieldKey, file)
    localForm.value[fieldKey + '_url'] = (updated as Record<string, unknown>)[fieldKey + '_url']
    emit('update:modelValue', localForm.value)
    toast.success('Logo uploaded')
  } catch (e) {
    console.error('Logo upload failed:', e)
    toast.error('Failed to upload logo')
  }
  input.value = ''
}

async function onLogoDelete(fieldKey: string) {
  try {
    await deleteLogo(fieldKey)
    localForm.value[fieldKey + '_url'] = null
    emit('update:modelValue', localForm.value)
    toast.success('Logo removed')
  } catch (e) {
    console.error('Logo delete failed:', e)
    toast.error('Failed to remove logo')
  }
}

function shallowEqual(a: Record<string, unknown>, b: Record<string, unknown>): boolean {
  const keysA = Object.keys(a)
  if (keysA.length !== Object.keys(b).length) return false
  return keysA.every((k) => a[k] === b[k])
}

watch(
  () => props.modelValue,
  (newForm) => {
    // Skip the echo: when the parent reassigns `form` because of our own
    // emit, newForm matches localForm field-for-field. Reassigning localForm
    // here would re-fire the deep watcher below, emit again, and run the
    // cycle. While Vue's batching settles it, fast `input` events that arrive
    // mid-cycle (Playwright fill, browser paste, autofill) get dropped.
    const sanitizedForm = omitRemovedSettings(newForm)
    if (shallowEqual(sanitizedForm, localForm.value)) return
    localForm.value = { ...sanitizedForm }
  },
)

const calendarField = ref<string | null>(null)

function openCalendar(field: string) {
  calendarField.value = field
  if (!localForm.value[field]) {
    const now = new Date()
    localForm.value[field] = now.toISOString()
  }
}
function closeCalendar() {
  calendarField.value = null
}
function onCalendarSelect(field: string, date: CalendarDateTime | null) {
  if (date && typeof date === 'object' && 'year' in date) {
    const jsDate = new Date(
      date.year,
      date.month - 1,
      date.day,
      date.hour || 0,
      date.minute || 0,
      date.second || 0,
    )
    localForm.value[field] = jsDate.toISOString()
  } else {
    localForm.value[field] = null
  }
  closeCalendar()
}
function formatDateTime(val: string | Date | null) {
  if (!val) return ''
  let d: Date | null = null
  if (typeof val === 'string') {
    d = new Date(val)
    if (isNaN(d.getTime())) return ''
  } else if (val instanceof Date) {
    d = val
  } else if (typeof val === 'object' && Object.prototype.hasOwnProperty.call(val, 'year')) {
    const anyVal = val as {
      year: number
      month: number
      day: number
      hour?: number
      minute?: number
      second?: number
    }
    d = new Date(
      anyVal.year,
      anyVal.month - 1,
      anyVal.day,
      anyVal.hour || 0,
      anyVal.minute || 0,
      anyVal.second || 0,
    )
  }
  if (!d || isNaN(d.getTime())) return ''
  return (
    d.toLocaleDateString(undefined, { day: '2-digit', month: '2-digit', year: 'numeric' }) +
    ' ' +
    d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit', hour12: false })
  )
}
function getValidDate(val: string | Date | null): CalendarDateTime | null {
  if (!val) return null
  if (val instanceof CalendarDateTime) return val
  if (typeof val === 'string') {
    try {
      return parseDateTime(val)
    } catch {
      const d = new Date(val)
      if (!isNaN(d.getTime())) return toCalendarDate(d)
      return null
    }
  }
  if (val instanceof Date && !isNaN(val.getTime())) return toCalendarDate(val)
  if (typeof val === 'object' && 'year' in val) return toCalendarDate(val)
  return null
}
function toCalendarDate(
  date:
    | Date
    | { year: number; month: number; day: number; hour?: number; minute?: number; second?: number },
): CalendarDateTime {
  if (date instanceof Date) {
    return new CalendarDateTime(
      date.getFullYear(),
      date.getMonth() + 1,
      date.getDate(),
      date.getHours(),
      date.getMinutes(),
      date.getSeconds(),
    )
  }
  return new CalendarDateTime(
    date.year,
    date.month,
    date.day,
    date.hour || 0,
    date.minute || 0,
    date.second || 0,
  )
}

const sectionFields = computed(() =>
  getFieldsForSection(props.section).filter((field) => !REMOVED_SETTING_KEYS.has(field.key)),
)
const isWorkingHours = computed(() => getSpecialHandler(props.section) === 'working_hours')

async function loadClientOptions() {
  clientOptionsLoading.value = true
  try {
    clientOptions.value = await api.clients_all_list()
  } catch (e) {
    console.error('Client options load failed:', e)
    toast.error('Failed to load clients')
  } finally {
    clientOptionsLoading.value = false
  }
}

watch(
  sectionFields,
  (fields) => {
    if (!fields.some((field) => field.type === 'client')) {
      return
    }

    if (clientOptions.value.length > 0) {
      return
    }

    void loadClientOptions()
  },
  { immediate: true },
)

function normalizeUrl(url: string): string {
  if (!url) return url
  if (/^https?:\/\//i.test(url)) return url
  return `https://${url}`
}

watch(
  localForm,
  (val) => {
    const normalized = { ...val }
    for (const field of sectionFields.value) {
      if (field.type === 'url' && normalized[field.key]) {
        normalized[field.key] = normalizeUrl(normalized[field.key] as string)
      }
    }
    emit('update:modelValue', normalized)
  },
  { deep: true },
)

const workingDays = [
  { key: 'monday', label: 'Monday', startKey: 'mon_start', endKey: 'mon_end' },
  { key: 'tuesday', label: 'Tuesday', startKey: 'tue_start', endKey: 'tue_end' },
  { key: 'wednesday', label: 'Wednesday', startKey: 'wed_start', endKey: 'wed_end' },
  { key: 'thursday', label: 'Thursday', startKey: 'thu_start', endKey: 'thu_end' },
  { key: 'friday', label: 'Friday', startKey: 'fri_start', endKey: 'fri_end' },
]

const workingHoursTimeKeys = new Set(workingDays.flatMap((d) => [d.startKey, d.endKey]))

function inputType(fieldType: string): 'number' | 'password' | 'text' {
  if (fieldType === 'number') return 'number'
  if (fieldType === 'password') return 'password'
  return 'text'
}

const genericFieldsForRender = computed(() => {
  if (!isWorkingHours.value) return sectionFields.value
  return sectionFields.value.filter((f) => !workingHoursTimeKeys.has(f.key))
})
</script>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
