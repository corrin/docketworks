<template>
  <form
    @submit.prevent="handleSubmit"
    class="flex flex-col gap-4"
    data-automation-id="DynamicFormEntry-form"
  >
    <!-- Entry date -->
    <div class="flex flex-col gap-1">
      <Label for="entry-date"> Entry Date <span class="text-destructive">*</span> </Label>
      <Input
        id="entry-date"
        type="date"
        :model-value="entryDate"
        data-automation-id="DynamicFormEntry-entry-date"
        @update:model-value="entryDate = String($event)"
      />
    </div>

    <!-- Dynamic fields -->
    <div
      v-for="field in schema.fields"
      :key="field.key"
      class="flex flex-col gap-1"
      :data-automation-id="`DynamicFormEntry-field-${field.key}`"
    >
      <Label :for="'field-' + field.key">
        {{ field.label }}
        <span v-if="field.required" class="text-destructive">*</span>
      </Label>

      <!-- Text -->
      <Input
        v-if="field.type === 'text'"
        :id="'field-' + field.key"
        type="text"
        :model-value="String(formData[field.key] ?? '')"
        @update:model-value="formData[field.key] = $event"
      />

      <!-- Textarea -->
      <Textarea
        v-else-if="field.type === 'textarea'"
        :id="'field-' + field.key"
        :model-value="String(formData[field.key] ?? '')"
        @update:model-value="formData[field.key] = $event"
      />

      <!-- Date -->
      <Input
        v-else-if="field.type === 'date'"
        :id="'field-' + field.key"
        type="date"
        :model-value="String(formData[field.key] ?? '')"
        @update:model-value="formData[field.key] = $event"
      />

      <!-- Boolean / Checkbox -->
      <div v-else-if="field.type === 'boolean'" class="flex items-center gap-2 pt-1">
        <Checkbox
          :id="'field-' + field.key"
          :checked="!!formData[field.key]"
          @update:checked="formData[field.key] = $event"
        />
        <Label :for="'field-' + field.key" class="text-sm font-normal cursor-pointer">
          {{ field.label }}
        </Label>
      </div>

      <!-- Number -->
      <Input
        v-else-if="field.type === 'number'"
        :id="'field-' + field.key"
        type="number"
        :model-value="formData[field.key] != null ? String(formData[field.key]) : ''"
        @update:model-value="formData[field.key] = $event === '' ? null : Number($event)"
      />

      <!-- Select -->
      <select
        v-else-if="field.type === 'select'"
        :id="'field-' + field.key"
        :value="String(formData[field.key] ?? '')"
        class="h-9 rounded-md border border-input bg-background px-3 py-1 text-sm shadow-xs focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] outline-none"
        @change="formData[field.key] = ($event.target as HTMLSelectElement).value"
      >
        <option value="" disabled>Select...</option>
        <option v-for="opt in field.options ?? []" :key="opt" :value="opt">
          {{ opt }}
        </option>
      </select>

      <!-- Validation error -->
      <p
        v-if="submitted && field.required && isFieldEmpty(field.key)"
        class="text-destructive text-xs"
      >
        {{ field.label }} is required
      </p>
    </div>

    <!-- Submit -->
    <div class="flex justify-end">
      <Button type="submit" :disabled="isSubmitting" data-automation-id="DynamicFormEntry-submit">
        <template v-if="isSubmitting">
          <Loader2 class="size-4 animate-spin" />
          Saving...
        </template>
        <span v-else>{{ initialData ? 'Update Entry' : 'Add Entry' }}</span>
      </Button>
    </div>
  </form>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { Loader2 } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Textarea } from '@/components/ui/textarea'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import type { FormSchema } from '@/types/processDocument.types'

interface Props {
  schema: FormSchema
  initialData?: Record<string, unknown>
  initialEntryDate?: string
  isSubmitting?: boolean
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'submit', payload: { entry_date: string; data: Record<string, unknown> }): void
}>()

function todayStr(): string {
  return new Date().toISOString().slice(0, 10)
}

const entryDate = ref(props.initialEntryDate ?? todayStr())
const formData = ref<Record<string, unknown>>({})
const submitted = ref(false)

// Initialize form data from initialData or defaults
function resetForm() {
  const data: Record<string, unknown> = {}
  for (const field of props.schema.fields) {
    if (props.initialData && props.initialData[field.key] !== undefined) {
      data[field.key] = props.initialData[field.key]
    } else {
      data[field.key] = field.type === 'boolean' ? false : ''
    }
  }
  formData.value = data
  entryDate.value = props.initialEntryDate ?? todayStr()
  submitted.value = false
}

// Watch for schema or initialData changes
watch(
  [() => props.schema, () => props.initialData, () => props.initialEntryDate],
  () => {
    resetForm()
  },
  { immediate: true, deep: true },
)

function isFieldEmpty(key: string): boolean {
  const val = formData.value[key]
  if (val === null || val === undefined || val === '') return true
  return false
}

function validate(): boolean {
  for (const field of props.schema.fields) {
    if (field.required && isFieldEmpty(field.key)) {
      return false
    }
  }
  if (!entryDate.value) return false
  return true
}

function handleSubmit() {
  submitted.value = true
  if (!validate()) return

  emit('submit', {
    entry_date: entryDate.value,
    data: { ...formData.value },
  })

  // Reset form after successful emit (for adding new entries)
  if (!props.initialData) {
    const data: Record<string, unknown> = {}
    for (const field of props.schema.fields) {
      data[field.key] = field.type === 'boolean' ? false : ''
    }
    formData.value = data
    entryDate.value = todayStr()
    submitted.value = false
  }
}
</script>
