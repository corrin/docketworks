<template>
  <Dialog :open="true" @update:open="handleClose">
    <DialogContent class="sm:max-w-[525px]">
      <DialogHeader>
        <DialogTitle>{{ isEditing ? 'Edit AI Provider' : 'Create AI Provider' }}</DialogTitle>
        <DialogDescription>
          {{
            isEditing
              ? 'Update the details for this AI provider.'
              : 'Add a new AI provider to the system.'
          }}
        </DialogDescription>
      </DialogHeader>

      <form @submit.prevent="onSubmit" class="grid gap-4 py-4">
        <!-- Name -->
        <div class="grid grid-cols-4 items-center gap-4">
          <Label for="name" class="text-right">Name</Label>
          <div class="col-span-3">
            <Input id="name" v-model="name" />
            <p v-if="errors.name" class="text-red-500 text-sm mt-1">{{ errors.name }}</p>
          </div>
        </div>

        <!-- Provider Type -->
        <div class="grid grid-cols-4 items-center gap-4">
          <Label for="provider_type" class="text-right">Provider Type</Label>
          <div class="col-span-3">
            <Select v-model="provider_type">
              <SelectTrigger>
                <SelectValue placeholder="Select a provider type" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="Claude">Anthropic (Claude)</SelectItem>
                <SelectItem value="Gemini">Google (Gemini)</SelectItem>
                <SelectItem value="Mistral">Mistral</SelectItem>
                <SelectItem value="OpenAI">OpenAI</SelectItem>
              </SelectContent>
            </Select>
            <p v-if="errors.provider_type" class="text-red-500 text-sm mt-1">
              {{ errors.provider_type }}
            </p>
          </div>
        </div>

        <!-- Model Name -->
        <div class="grid grid-cols-4 items-center gap-4">
          <Label for="model_name" class="text-right">Model Name</Label>
          <div class="col-span-3">
            <Input
              id="model_name"
              v-model="model_name"
              placeholder="e.g., gemini-2.5-flash-lite-preview-06-17"
            />
            <p v-if="errors.model_name" class="text-red-500 text-sm mt-1">
              {{ errors.model_name }}
            </p>
          </div>
        </div>

        <!-- API Key -->
        <div class="grid grid-cols-4 items-center gap-4">
          <Label for="api_key" class="text-right">API Key</Label>
          <div class="col-span-3">
            <Input
              id="api_key"
              type="password"
              v-model="api_key"
              :placeholder="isEditing ? 'Leave blank to keep unchanged' : 'Enter API Key'"
            />
            <p v-if="errors.api_key" class="text-red-500 text-sm mt-1">{{ errors.api_key }}</p>
          </div>
        </div>

        <!-- Is Default -->
        <div class="grid grid-cols-4 items-center gap-4">
          <Label for="default" class="text-right">Default</Label>
          <div class="col-span-3 flex items-center">
            <Switch id="default" :checked="is_default" @update:checked="is_default = $event" />
            <span class="ml-2 text-sm text-gray-600">Set as default provider</span>
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" @click="handleClose">Cancel</Button>
          <Button type="submit" :disabled="isSubmitting">
            {{ isSubmitting ? 'Saving...' : 'Save Changes' }}
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useForm } from 'vee-validate'
import { toTypedSchema } from '@vee-validate/zod'
import * as z from 'zod'

import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { AIProvider } from '@/services/aiProviderService'

const props = defineProps<{
  provider: AIProvider | null
}>()

const emit = defineEmits(['close', 'save'])

const isEditing = computed(() => !!props.provider)

const baseSchema = z
  .object({
    id: z.number().optional().nullable(),
    name: z.string().min(1, 'Name is required'),
    provider_type: z.enum(['Claude', 'Gemini', 'Mistral', 'OpenAI'], {
      required_error: 'Provider type is required',
    }),
    model_name: z.string().optional(),
    api_key: z.string().optional(),
    default: z.boolean().default(false),
  })
  .refine((data) => (!isEditing.value ? !!data.api_key : true), {
    message: 'API Key is required for new providers',
    path: ['api_key'],
  })

type FormValues = z.input<typeof baseSchema>
const formSchema = toTypedSchema(baseSchema)

const { handleSubmit, defineField, errors, isSubmitting } = useForm<FormValues>({
  validationSchema: formSchema,
  initialValues: {
    id: props.provider?.id ?? null,
    name: props.provider?.name ?? '',
    provider_type: props.provider?.provider_type ?? 'Gemini',
    model_name: props.provider?.model_name ?? '',
    api_key: '',
    default: props.provider?.default ?? false,
  } satisfies FormValues,
})

const [name] = defineField('name')
const [provider_type] = defineField('provider_type')
const [model_name] = defineField('model_name')
const [api_key] = defineField('api_key')
const [is_default] = defineField('default')

const onSubmit = handleSubmit((values) => {
  const dataToSave = { ...values }

  if (isEditing.value && !dataToSave.api_key) {
    delete dataToSave.api_key
  }

  emit('save', dataToSave)
})

const handleClose = () => {
  emit('close')
}
</script>
