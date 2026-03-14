<template>
  <Dialog :open="true" @update:open="handleClose">
    <DialogContent class="max-w-2xl space-y-6 animate-in fade-in-0 zoom-in-95">
      <DialogHeader>
        <DialogTitle>Edit Company Defaults</DialogTitle>
      </DialogHeader>
      <form @submit.prevent="submitForm" class="space-y-4">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label class="block text-sm font-medium mb-1">Company Name</label>
            <input v-model="form.company_name" class="input" required />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Charge Out Rate</label>
            <input v-model.number="form.charge_out_rate" type="number" class="input" required />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Wage Rate</label>
            <input v-model.number="form.wage_rate" type="number" class="input" required />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Time Markup</label>
            <input v-model.number="form.time_markup" type="number" class="input" required />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Materials Markup</label>
            <input v-model.number="form.materials_markup" type="number" class="input" required />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Starting Job Number</label>
            <input v-model.number="form.starting_job_number" type="number" class="input" required />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">PO Prefix</label>
            <input v-model="form.po_prefix" class="input" required />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1">Shop Client Name</label>
            <input v-model="form.shop_client_name" class="input" />
          </div>
        </div>
        <div class="flex gap-2 justify-end mt-4">
          <Button type="button" variant="outline" @click="handleClose" :disabled="isLoading"
            >Cancel</Button
          >
          <Button type="submit" variant="default" :disabled="isLoading">
            <div v-if="isLoading" class="flex items-center gap-2">
              <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
              Saving...
            </div>
            <span v-else>Save</span>
          </Button>
        </div>
        <p v-if="error" class="text-red-600 text-sm mt-2">{{ error }}</p>
      </form>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import Dialog from '@/components/ui/dialog/Dialog.vue'
import DialogContent from '@/components/ui/dialog/DialogContent.vue'
import DialogHeader from '@/components/ui/dialog/DialogHeader.vue'
import DialogTitle from '@/components/ui/dialog/DialogTitle.vue'
import Button from '@/components/ui/button/Button.vue'
import { ref, watch } from 'vue'
import { updateCompanyDefaults } from '@/services/admin-company-defaults-service'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type CompanyDefaultsForm = z.infer<typeof schemas.CompanyDefaults>

const props = defineProps<{ defaults: CompanyDefaultsForm }>()
const emit = defineEmits(['close', 'saved'])
const form = ref<CompanyDefaultsForm>({ ...props.defaults })
const error = ref('')
const isLoading = ref(false)

watch(
  () => props.defaults,
  (val) => {
    form.value = { ...val }
  },
)

function handleClose() {
  emit('close')
}

async function submitForm() {
  error.value = ''
  isLoading.value = true
  try {
    await updateCompanyDefaults(form.value)
    emit('saved')
  } catch {
    error.value = 'Failed to save company defaults.'
  } finally {
    isLoading.value = false
  }
}
</script>

<style scoped>
.input {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: 1px solid #c7d2fe;
  border-radius: 0.5rem;
  background: #f8fafc;
  font-size: 1rem;
  transition: border 0.2s;
}
.input:focus {
  border-color: #6366f1;
  outline: none;
}
</style>
