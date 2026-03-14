<template>
  <Dialog :open="open" @update:open="onOpenChange">
    <DialogContent
      class="max-w-md animate-in fade-in-0 zoom-in-95"
      data-automation-id="ProcessDocumentModal-container"
    >
      <DialogHeader>
        <DialogTitle
          >{{ isEditing ? 'Edit' : 'New' }} {{ isForm ? 'Form' : 'Procedure' }}</DialogTitle
        >
      </DialogHeader>
      <form @submit.prevent="submitForm" class="flex flex-col gap-4 mt-2">
        <!-- Title -->
        <label class="flex flex-col gap-1">
          <span class="font-medium text-sm">Title</span>
          <Input
            v-model="form.title"
            placeholder="Document title"
            required
            data-automation-id="ProcessDocumentModal-title"
          />
        </label>

        <!-- Document # -->
        <label class="flex flex-col gap-1">
          <span class="font-medium text-sm">Document #</span>
          <Input
            v-model="form.document_number"
            placeholder="Optional document number"
            data-automation-id="ProcessDocumentModal-document-number"
          />
        </label>

        <!-- Tags -->
        <label class="flex flex-col gap-1">
          <span class="font-medium text-sm">Tags</span>
          <Input
            v-model="form.tags"
            placeholder="Comma-separated tags"
            data-automation-id="ProcessDocumentModal-tags"
          />
        </label>

        <!-- Site location (procedures only) -->
        <label v-if="!isForm" class="flex flex-col gap-1">
          <span class="font-medium text-sm">Site Location</span>
          <Input
            v-model="form.site_location"
            placeholder="Work site location"
            data-automation-id="ProcessDocumentModal-site-location"
          />
        </label>

        <!-- Form Schema (JSON) — for forms -->
        <label v-if="isForm" class="flex flex-col gap-1">
          <span class="font-medium text-sm">Form Schema (JSON)</span>
          <textarea
            v-model="form.form_schema"
            class="border border-input rounded-md p-2 text-xs font-mono bg-background shadow-xs focus-visible:border-ring focus-visible:ring-ring/50 focus-visible:ring-[3px] outline-none"
            data-automation-id="ProcessDocumentModal-form-schema"
            rows="6"
            placeholder='{"fields": [{"key": "name", "label": "Name", "type": "text"}]}'
          />
          <span v-if="schemaError" class="text-destructive text-xs">{{ schemaError }}</span>
        </label>

        <!-- Actions -->
        <div class="flex justify-end gap-2 mt-2">
          <Button
            type="button"
            variant="outline"
            @click="emit('close')"
            :disabled="isSubmitting"
            data-automation-id="ProcessDocumentModal-cancel"
          >
            Cancel
          </Button>
          <Button
            type="submit"
            :disabled="isSubmitting"
            data-automation-id="ProcessDocumentModal-submit"
          >
            <div v-if="isSubmitting" class="flex items-center gap-2">
              <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
              {{ isEditing ? 'Saving...' : 'Creating...' }}
            </div>
            <span v-else>{{ isEditing ? 'Save Changes' : 'Create Document' }}</span>
          </Button>
        </div>
      </form>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { toast } from 'vue-sonner'
import { useProcessDocumentsStore } from '@/stores/processDocuments'
import Dialog from '@/components/ui/dialog/Dialog.vue'
import DialogContent from '@/components/ui/dialog/DialogContent.vue'
import DialogHeader from '@/components/ui/dialog/DialogHeader.vue'
import DialogTitle from '@/components/ui/dialog/DialogTitle.vue'
import Button from '@/components/ui/button/Button.vue'
import Input from '@/components/ui/input/Input.vue'

interface EditableDocument {
  id: string
  title: string
  document_number?: string | null
  tags?: string[] | unknown
  site_location?: string
}

interface Props {
  open: boolean
  documentType: 'forms' | 'procedures'
  category: string
  editDocument?: EditableDocument | null
}

interface FormState {
  title: string
  document_number: string
  tags: string
  form_schema: string
  site_location: string
}

const props = withDefaults(defineProps<Props>(), {
  editDocument: null,
})

const isEditing = computed(() => !!props.editDocument)

const emit = defineEmits<{
  (e: 'close'): void
  (e: 'saved'): void
}>()

const store = useProcessDocumentsStore()

const isForm = computed(() => props.documentType === 'forms')
const isSubmitting = ref(false)
const schemaError = ref<string | null>(null)

const emptyForm: FormState = {
  title: '',
  document_number: '',
  tags: '',
  form_schema: '',
  site_location: '',
}

const form = ref<FormState>({ ...emptyForm })

// Reset or populate form when modal opens
watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      schemaError.value = null
      if (props.editDocument) {
        const doc = props.editDocument
        const tags = Array.isArray(doc.tags)
          ? doc.tags.filter((t): t is string => typeof t === 'string')
          : []
        form.value = {
          title: doc.title || '',
          document_number: doc.document_number || '',
          tags: tags.join(', '),
          form_schema: '',
          site_location: ('site_location' in doc ? (doc.site_location as string) : '') || '',
        }
      } else {
        form.value = { ...emptyForm }
      }
    }
  },
)

function onOpenChange(open: boolean) {
  if (!open) {
    emit('close')
  }
}

function parseTags(input: string): string[] {
  return input
    .split(',')
    .map((t) => t.trim())
    .filter((t) => t.length > 0)
}

function validateFormSchema(json: string): unknown | null {
  try {
    const parsed = JSON.parse(json)
    schemaError.value = null
    return parsed
  } catch {
    schemaError.value = 'Invalid JSON'
    return null
  }
}

async function submitForm() {
  isSubmitting.value = true

  try {
    if (isEditing.value && props.editDocument) {
      if (isForm.value) {
        await store.updateForm(props.category, props.editDocument.id, {
          title: form.value.title,
          document_number: form.value.document_number || '',
          tags: parseTags(form.value.tags),
        })
      } else {
        await store.updateProcedure(props.category, props.editDocument.id, {
          title: form.value.title,
          document_number: form.value.document_number || '',
          tags: parseTags(form.value.tags),
          site_location: form.value.site_location || '',
        })
      }
    } else {
      if (isForm.value) {
        // Validate form schema JSON if provided
        let formSchema: unknown = undefined
        if (form.value.form_schema.trim()) {
          formSchema = validateFormSchema(form.value.form_schema)
          if (formSchema === null) {
            isSubmitting.value = false
            return
          }
        }

        await store.createForm(props.category, {
          title: form.value.title,
          document_number: form.value.document_number || '',
          tags: parseTags(form.value.tags),
          form_schema: formSchema,
        })
      } else {
        await store.createProcedure(props.category, {
          title: form.value.title,
          document_number: form.value.document_number || '',
          tags: parseTags(form.value.tags),
          site_location: form.value.site_location || '',
        })
      }
    }

    emit('saved')
    emit('close')
  } catch (error) {
    console.error('Error saving document:', error)
    toast.error('Failed to save document')
  } finally {
    isSubmitting.value = false
  }
}
</script>

<style scoped>
textarea {
  resize: vertical;
}
</style>
