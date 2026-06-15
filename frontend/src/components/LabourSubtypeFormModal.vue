<template>
  <Dialog :open="true" @update:open="handleClose">
    <DialogContent
      class="max-w-lg space-y-6 animate-in fade-in-0 zoom-in-95"
      data-automation-id="LabourSubtypeFormModal-container"
    >
      <DialogHeader>
        <DialogTitle>{{ subtype ? 'Edit Labour Rate' : 'New Labour Subtype' }}</DialogTitle>
      </DialogHeader>
      <form @submit.prevent="submitForm" class="space-y-4">
        <!-- Name: only editable on create -->
        <div v-if="!subtype">
          <label class="block text-sm font-medium mb-1" for="name">Name</label>
          <Input
            id="name"
            v-model="form.name"
            placeholder="Name"
            data-automation-id="LabourSubtypeFormModal-name"
            required
          />
        </div>
        <div v-else>
          <label class="block text-sm font-medium mb-1">Name</label>
          <Input
            :model-value="subtype.name"
            type="text"
            disabled
            class="bg-gray-100 text-gray-500"
          />
        </div>

        <!-- Default charge-out rate: editable on create and edit -->
        <div>
          <label class="block text-sm font-medium mb-1" for="default_charge_out_rate">
            Default Charge-Out Rate (NZD/hour)
          </label>
          <Input
            id="default_charge_out_rate"
            v-model.number="form.default_charge_out_rate"
            type="number"
            min="0"
            step="0.01"
            placeholder="Default Charge-Out Rate"
            data-automation-id="LabourSubtypeFormModal-rate"
            required
          />
        </div>

        <!-- Create-only fields -->
        <template v-if="!subtype">
          <div>
            <label class="block text-sm font-medium mb-1" for="display_order">Display Order</label>
            <Input
              id="display_order"
              v-model.number="form.display_order"
              type="number"
              min="0"
              step="1"
              placeholder="Display Order"
            />
          </div>
          <div class="flex gap-6 items-center">
            <label class="flex items-center gap-2">
              <input type="checkbox" v-model="form.is_workshop" /> Workshop
            </label>
            <label class="flex items-center gap-2">
              <input type="checkbox" v-model="form.counts_for_scheduling" /> Counts for scheduling
            </label>
          </div>
        </template>

        <!-- Edit-only: active flag -->
        <div v-else class="flex items-center gap-2">
          <label class="flex items-center gap-2">
            <input
              type="checkbox"
              v-model="form.is_active"
              data-automation-id="LabourSubtypeFormModal-active"
            />
            Active
          </label>
        </div>

        <p v-if="error" class="text-sm text-red-600 whitespace-pre-line">{{ error }}</p>

        <DialogFooter class="flex gap-2 justify-end">
          <Button variant="ghost" type="button" @click="handleClose" :disabled="isLoading">
            Cancel
          </Button>
          <Button
            type="submit"
            :disabled="isLoading"
            data-automation-id="LabourSubtypeFormModal-submit"
          >
            <div v-if="isLoading" class="flex items-center gap-2">
              <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
              {{ subtype ? 'Saving...' : 'Creating...' }}
            </div>
            <span v-else>{{ subtype ? 'Save Changes' : 'Create Subtype' }}</span>
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import Dialog from '@/components/ui/dialog/Dialog.vue'
import DialogContent from '@/components/ui/dialog/DialogContent.vue'
import DialogHeader from '@/components/ui/dialog/DialogHeader.vue'
import DialogTitle from '@/components/ui/dialog/DialogTitle.vue'
import DialogFooter from '@/components/ui/dialog/DialogFooter.vue'
import Button from '@/components/ui/button/Button.vue'
import Input from '@/components/ui/input/Input.vue'
import { ref, watch } from 'vue'
import { z } from 'zod'
import { schemas } from '../api/generated/api'
import { useLabourSubtypesApi } from '@/composables/useLabourSubtypesApi'
import { toast } from 'vue-sonner'

type LabourSubtype = z.infer<typeof schemas.LabourSubtypeManage>

/**
 * Pull DRF field-level validation messages out of a 400 response body shaped
 * like {"is_active": ["N staff default to '<name>'; reassign them ..."]}.
 * Returns null when the error is not a recognisable field-error payload.
 */
function extractFieldErrors(e: unknown): string | null {
  if (!e || typeof e !== 'object' || !('isAxiosError' in e)) return null
  const axiosError = e as { response?: { data?: unknown } }
  const data = axiosError.response?.data
  if (!data || typeof data !== 'object') return null
  const messages: string[] = []
  for (const value of Object.values(data as Record<string, unknown>)) {
    if (Array.isArray(value)) {
      messages.push(...value.map((v) => String(v)))
    } else if (typeof value === 'string') {
      messages.push(value)
    } else {
      // Non-string, non-array field value — ignore; not a user-facing message.
    }
  }
  return messages.length ? messages.join('\n') : null
}

const props = defineProps<{ subtype: LabourSubtype | null }>()
const emit = defineEmits(['close', 'saved'])

const isLoading = ref(false)
const error = ref('')
const { createLabourSubtype, updateLabourSubtype } = useLabourSubtypesApi()

const form = ref({
  name: '',
  default_charge_out_rate: 0,
  display_order: 0,
  is_workshop: false,
  counts_for_scheduling: false,
  is_active: true,
})

watch(
  () => props.subtype,
  (subtype) => {
    if (subtype) {
      form.value = {
        name: subtype.name,
        default_charge_out_rate: subtype.default_charge_out_rate ?? 0,
        display_order: subtype.display_order ?? 0,
        is_workshop: subtype.is_workshop ?? false,
        counts_for_scheduling: subtype.counts_for_scheduling ?? false,
        is_active: subtype.is_active ?? true,
      }
    } else {
      form.value = {
        name: '',
        default_charge_out_rate: 0,
        display_order: 0,
        is_workshop: false,
        counts_for_scheduling: false,
        is_active: true,
      }
    }
    error.value = ''
  },
  { immediate: true },
)

function handleClose() {
  emit('close')
}

async function submitForm() {
  error.value = ''
  isLoading.value = true

  try {
    if (props.subtype) {
      // Edit: only the rate and active flag may change on an existing subtype.
      const update: z.infer<typeof schemas.PatchedLabourSubtypeManageRequest> = {
        default_charge_out_rate: form.value.default_charge_out_rate,
        is_active: form.value.is_active,
      }
      await updateLabourSubtype(props.subtype.id, update)
      toast.success('Labour rate updated successfully!')
    } else {
      const create: z.infer<typeof schemas.LabourSubtypeManageRequest> = {
        name: form.value.name.trim(),
        default_charge_out_rate: form.value.default_charge_out_rate,
        display_order: form.value.display_order,
        is_workshop: form.value.is_workshop,
        counts_for_scheduling: form.value.counts_for_scheduling,
      }
      await createLabourSubtype(create)
      toast.success('Labour subtype created successfully!')
    }
    emit('saved')
  } catch (e) {
    const fieldErrors = extractFieldErrors(e)
    if (fieldErrors) {
      error.value = fieldErrors
      toast.error(fieldErrors)
    } else if (e instanceof Error) {
      error.value = e.message
      toast.error(e.message)
    } else {
      error.value = 'Failed to save labour subtype.'
      toast.error('Failed to save labour subtype.')
    }
  } finally {
    isLoading.value = false
  }
}
</script>

<style scoped>
.animate-in {
  animation: fadeInZoom 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes fadeInZoom {
  from {
    opacity: 0;
    transform: scale(0.95);
  }

  to {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
