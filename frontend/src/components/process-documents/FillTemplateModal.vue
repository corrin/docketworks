<template>
  <Dialog :open="open" @update:open="onOpenChange">
    <DialogContent class="max-w-md" data-automation-id="FillTemplateModal-container">
      <DialogHeader>
        <DialogTitle>Fill form {{ template?.title ?? '' }}</DialogTitle>
        <DialogDescription> A new entry will be created from this form. </DialogDescription>
      </DialogHeader>

      <form @submit.prevent="handleSubmit" class="flex flex-col gap-4 mt-2">
        <!-- Job ID (optional) -->
        <label class="flex flex-col gap-1">
          <span class="font-medium text-sm">Link to job (optional)</span>
          <Input
            v-model="jobId"
            placeholder="Paste a job ID to link this entry"
            data-automation-id="FillTemplateModal-job-id"
          />
        </label>

        <!-- Actions -->
        <DialogFooter>
          <Button
            type="button"
            variant="outline"
            :disabled="isSubmitting"
            data-automation-id="FillTemplateModal-cancel"
            @click="emit('close')"
          >
            Cancel
          </Button>
          <Button
            type="submit"
            :disabled="isSubmitting"
            data-automation-id="FillTemplateModal-submit"
          >
            <template v-if="isSubmitting">
              <Loader2 class="size-4 animate-spin" />
              Creating...
            </template>
            <span v-else>Create</span>
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { Loader2 } from 'lucide-vue-next'
import { Dialog } from '@/components/ui/dialog'
import DialogContent from '@/components/ui/dialog/DialogContent.vue'
import DialogHeader from '@/components/ui/dialog/DialogHeader.vue'
import DialogTitle from '@/components/ui/dialog/DialogTitle.vue'
import DialogDescription from '@/components/ui/dialog/DialogDescription.vue'
import DialogFooter from '@/components/ui/dialog/DialogFooter.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useProcessDocumentsStore } from '@/stores/processDocuments'
import type { FormListItem, FormDetail } from '@/types/processDocument.types'

interface Props {
  open: boolean
  template: FormListItem | FormDetail | null
  category: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'filled'): void
}>()

const router = useRouter()
const store = useProcessDocumentsStore()

const jobId = ref('')
const isSubmitting = ref(false)

// Reset form when modal opens
watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      jobId.value = ''
    }
  },
)

function onOpenChange(open: boolean) {
  if (!open) {
    emit('close')
  }
}

async function handleSubmit() {
  if (!props.template) return

  isSubmitting.value = true
  try {
    const entry = await store.fillForm(
      props.category,
      props.template.id,
      jobId.value.trim() || undefined,
    )

    if (!entry) return

    // Navigate to the form's entries view
    router.push(`/process-documents/forms/${props.category}/${props.template.id}`)

    emit('filled')
    emit('close')
  } finally {
    isSubmitting.value = false
  }
}
</script>
