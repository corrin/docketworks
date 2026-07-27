<template>
  <Dialog :open="true" @update:open="handleClose">
    <DialogContent class="sm:max-w-[525px]">
      <DialogHeader>
        <DialogTitle>{{
          isEditing ? 'Edit NotebookLM Link' : 'Create NotebookLM Link'
        }}</DialogTitle>
        <DialogDescription>
          {{
            isEditing
              ? 'Update the details for this NotebookLM link.'
              : 'Add a new NotebookLM link to the training menu.'
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

        <!-- URL -->
        <div class="grid grid-cols-4 items-center gap-4">
          <Label for="url" class="text-right">URL</Label>
          <div class="col-span-3">
            <Input
              id="url"
              type="url"
              v-model="url"
              placeholder="https://notebooklm.google.com/..."
            />
            <p v-if="errors.url" class="text-red-500 text-sm mt-1">{{ errors.url }}</p>
          </div>
        </div>

        <!-- Restriction -->
        <div class="grid grid-cols-4 items-center gap-4">
          <Label for="restriction" class="text-right">Restriction</Label>
          <div class="col-span-3">
            <Select v-model="restriction">
              <SelectTrigger>
                <SelectValue placeholder="Select a restriction" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="none">None</SelectItem>
                <SelectItem value="superuser">Superusers only</SelectItem>
              </SelectContent>
            </Select>
            <p v-if="errors.restriction" class="text-red-500 text-sm mt-1">
              {{ errors.restriction }}
            </p>
          </div>
        </div>

        <!-- Order -->
        <div class="grid grid-cols-4 items-center gap-4">
          <Label for="order" class="text-right">Order</Label>
          <div class="col-span-3">
            <Input id="order" type="number" v-model.number="order" />
            <p v-if="errors.order" class="text-red-500 text-sm mt-1">{{ errors.order }}</p>
          </div>
        </div>

        <!-- Enabled -->
        <div class="grid grid-cols-4 items-center gap-4">
          <Label for="enabled" class="text-right">Enabled</Label>
          <div class="col-span-3 flex items-center">
            <Switch id="enabled" :checked="enabled" @update:checked="enabled = $event" />
            <span class="ml-2 text-sm text-gray-600">Show this link in the training menu</span>
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
import type { NotebookLmLink } from '@/services/notebookLmLinkService'

const props = defineProps<{
  link: NotebookLmLink | null
}>()

const emit = defineEmits(['close', 'save'])

const isEditing = computed(() => !!props.link)

const baseSchema = z.object({
  id: z.number().optional().nullable(),
  name: z.string().min(1, 'Name is required'),
  url: z.string().min(1, 'URL is required').url('Enter a valid URL'),
  enabled: z.boolean().default(true),
  restriction: z.enum(['none', 'superuser'], {
    required_error: 'Restriction is required',
  }),
  order: z.number({ invalid_type_error: 'Order must be a number' }).int(),
})

type FormValues = z.input<typeof baseSchema>
const formSchema = toTypedSchema(baseSchema)

const { handleSubmit, defineField, errors, isSubmitting } = useForm<FormValues>({
  validationSchema: formSchema,
  initialValues: {
    id: props.link?.id ?? null,
    name: props.link?.name ?? '',
    url: props.link?.url ?? '',
    enabled: props.link?.enabled ?? true,
    restriction: props.link?.restriction ?? 'none',
    order: props.link?.order ?? 0,
  } satisfies FormValues,
})

const [name] = defineField('name')
const [url] = defineField('url')
const [enabled] = defineField('enabled')
const [restriction] = defineField('restriction')
const [order] = defineField('order')

const onSubmit = handleSubmit((values) => {
  emit('save', { ...values })
})

const handleClose = () => {
  emit('close')
}
</script>
