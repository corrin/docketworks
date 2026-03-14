<template>
  <Dialog :open="true" @update:open="emit('close')">
    <DialogContent
      :class="['animate-in fade-in-0 zoom-in-95', hasEmbedded ? 'max-w-3xl' : 'max-w-md']"
      data-automation-id="SectionModal-content"
    >
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <component :is="sectionIcon" class="w-6 h-6" />
          {{ sectionTitle }}
        </DialogTitle>
        <DialogDescription> Edit company defaults for {{ sectionTitle }} </DialogDescription>
      </DialogHeader>
      <form @submit.prevent class="flex flex-col gap-4 mt-2">
        <template v-if="isWorkingHours">
          <div v-for="day in workingDays" :key="day.key" class="working-hours-day-wrapper">
            <div class="working-hours-day-label">
              <component :is="Clock" class="w-4 h-4 text-indigo-400 mr-1" />
              <span class="font-semibold">{{ day.label }}</span>
            </div>
            <div class="flex gap-2 items-center mt-1">
              <label class="flex items-center gap-1 text-xs font-medium">
                Start
                <Input
                  v-model="localForm[day.startKey] as string"
                  type="text"
                  class="h-8 w-40 text-xs"
                  placeholder="08:00"
                />
              </label>
              <span class="text-gray-400">-</span>
              <label class="flex items-center gap-1 text-xs font-medium">
                End
                <Input
                  v-model="localForm[day.endKey] as string"
                  type="text"
                  class="h-8 w-40 text-xs"
                  placeholder="17:00"
                />
              </label>
            </div>
          </div>
        </template>
        <template v-else>
          <template v-for="field in sectionFields" :key="field.key">
            <label class="flex items-center gap-2 text-sm font-medium">
              <component :is="field.icon" class="w-4 h-4 text-indigo-400" />
              <span class="w-36">{{ field.label }}</span>
              <Checkbox
                v-if="field.type === 'boolean'"
                v-model="localForm[field.key] as boolean | null | undefined"
              />
              <div v-else-if="field.type === 'date'" class="flex-1 relative">
                <Input
                  :modelValue="formatDateTime(localForm[field.key] as string | Date | null)"
                  type="text"
                  class="h-8 text-xs cursor-pointer bg-white"
                  readonly
                  @focus="openCalendar(field.key)"
                  @click="openCalendar(field.key)"
                />
                <transition name="fade">
                  <div
                    v-if="calendarField === field.key"
                    class="absolute z-50 left-0 bottom-10 w-max min-w-[260px] bg-white border border-gray-200 rounded-lg shadow-lg p-4"
                    @click.stop
                  >
                    <!-- 'as any' needed: Calendar expects specific date type, getValidDate returns CalendarDateTime | null -->
                    <Calendar
                      :modelValue="
                        (getValidDate(localForm[field.key] as string | Date | null) ||
                          getValidDate(props.form[field.key] as string | Date | null)) as any
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
              <Input
                v-else
                v-model="localForm[field.key] as string | number | undefined"
                :type="field.type === 'number' ? 'number' : 'text'"
                class="flex-1 h-8 text-xs"
                :class="[
                  { 'bg-gray-100 cursor-not-allowed': field.readOnly },
                  logFallbackInput(field),
                ]"
                :data-automation-id="`SectionModal-${section}-field-${field.key}`"
                :readonly="field.readOnly"
                :step="
                  field.key === 'time_markup' || field.key === 'materials_markup'
                    ? 'any'
                    : undefined
                "
                :min="
                  field.key === 'time_markup' || field.key === 'materials_markup' ? 0 : undefined
                "
                :max="
                  field.key === 'time_markup' || field.key === 'materials_markup' ? 1 : undefined
                "
              />
            </label>
          </template>
        </template>
        <p v-if="error" class="text-red-600 text-xs mt-1">{{ error }}</p>

        <!-- Embedded components (registered in embeddedComponentRegistry.ts) -->
        <template v-if="embeddedComponents.length > 0">
          <div class="border-t pt-4 mt-4">
            <component v-for="(comp, idx) in embeddedComponents" :key="idx" :is="comp" />
          </div>
        </template>

        <div class="flex justify-end gap-2 mt-2">
          <Button
            type="button"
            variant="outline"
            :data-automation-id="`SectionModal-${section}-close-button`"
            @click="emit('close')"
            class="flex items-center gap-1"
          >
            <ArrowLeft class="w-4 h-4" /> Close
          </Button>
        </div>
      </form>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import Dialog from '@/components/ui/dialog/Dialog.vue'
import DialogContent from '@/components/ui/dialog/DialogContent.vue'
import DialogHeader from '@/components/ui/dialog/DialogHeader.vue'
import DialogTitle from '@/components/ui/dialog/DialogTitle.vue'
import DialogDescription from '@/components/ui/dialog/DialogDescription.vue'
import Button from '@/components/ui/button/Button.vue'
import Input from '@/components/ui/input/Input.vue'
import Checkbox from '@/components/ui/checkbox/Checkbox.vue'
import Calendar from '@/components/ui/calendar/Calendar.vue'
import { ArrowLeft, Clock, HelpCircle } from 'lucide-vue-next'
import { ref, computed, watch } from 'vue'
import { CalendarDateTime, parseDateTime } from '@internationalized/date'
import { debugLog } from '@/utils/debug'
import { useSettingsSchema } from '@/composables/useSettingsSchema'
import { getEmbeddedComponents, hasEmbeddedComponents } from '@/utils/embeddedComponentRegistry'

const props = defineProps<{ section: string; form: Record<string, unknown> }>()

const { getSectionByKey, getFieldsForSection, getSpecialHandler } = useSettingsSchema()
const emit = defineEmits(['close', 'update'])
const localForm = ref({ ...props.form })

// Debug logging for type issues
debugLog('SectionModal props.section:', props.section, 'type:', typeof props.section)
debugLog('SectionModal props.form:', props.form)
debugLog('SectionModal localForm initial:', localForm.value)

// Log when fallback input is rendered for non-text/number types
function logFallbackInput(field: { key: string; type: string; label: string }) {
  if (field.type !== 'text' && field.type !== 'number') {
    console.log(
      `[SectionModal] Fallback Input rendered for field "${field.key}" (type: ${field.type}, label: ${field.label})`,
    )
  }
  return {} // Return empty object for class binding
}

watch(
  () => props.form,
  (newForm) => {
    localForm.value = { ...newForm }
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
  } else if (
    typeof val === 'object' &&
    val !== null &&
    Object.prototype.hasOwnProperty.call(val, 'year')
  ) {
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

// Get section data from schema
const currentSection = computed(() => getSectionByKey(props.section))
const sectionTitle = computed(() => currentSection.value?.title || '')
const sectionIcon = computed(() => currentSection.value?.icon || HelpCircle)
const sectionFields = computed(() => getFieldsForSection(props.section))
const isWorkingHours = computed(() => getSpecialHandler(props.section) === 'working_hours')
const error = ref('')

// Embedded components for this section
const embeddedComponents = computed(() => getEmbeddedComponents(props.section))
const hasEmbedded = computed(() => hasEmbeddedComponents(props.section))

// Normalize URL: add https:// if missing
function normalizeUrl(url: string): string {
  if (!url) return url
  if (/^https?:\/\//i.test(url)) return url
  return `https://${url}`
}

watch(
  localForm,
  (val) => {
    // Normalize URL fields before emitting
    const normalized = { ...val }
    for (const field of sectionFields.value) {
      if (field.type === 'url' && normalized[field.key]) {
        normalized[field.key] = normalizeUrl(normalized[field.key] as string)
      }
    }
    emit('update', normalized)
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
</script>

<style scoped>
label {
  gap: 0.5rem;
}

.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

[data-calendar-popup] {
  bottom: 2.5rem !important;
  top: auto !important;
}

.working-hours-day-wrapper {
  background: linear-gradient(90deg, #eef2ff 0%, #f8fafc 100%);
  border-radius: 0.75rem;
  box-shadow: 0 1px 4px 0 rgba(80, 80, 120, 0.06);
  padding: 0.65rem 1rem;
  margin-bottom: 0.35rem;
  display: flex;
  flex-direction: column;
  gap: 0.15rem;
}

.working-hours-day-label {
  display: flex;
  align-items: center;
  font-size: 1rem;
  color: #3730a3;
  margin-bottom: 0.15rem;
}
</style>
