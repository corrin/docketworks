<script setup lang="ts">
import { computed } from 'vue'
import { useVModel } from '@vueuse/core'
import Input from '@/components/ui/input/Input.vue'
import { Button } from '@/components/ui/button'
import Label from '@/components/ui/label/Label.vue'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { SystemErrorFilterState } from '@/types/errorFilters'

const defaultState: SystemErrorFilterState = {
  app: '',
  severity: '',
  resolved: 'all',
  jobId: '',
  userId: '',
}

const props = defineProps<{ modelValue: SystemErrorFilterState }>()
const emit = defineEmits<{ 'update:modelValue': [SystemErrorFilterState] }>()

const model = useVModel(props, 'modelValue', emit)

const hasActiveFilters = computed(() => {
  const value = model.value
  return (
    !!value.app.trim() ||
    !!value.severity.trim() ||
    value.resolved !== 'all' ||
    !!value.jobId.trim() ||
    !!value.userId.trim()
  )
})

function resetFilters() {
  model.value = { ...defaultState }
}
</script>

<template>
  <div class="grid gap-4 md:grid-cols-[repeat(auto-fit,minmax(200px,1fr))] items-end">
    <div class="flex flex-col gap-2">
      <Label for="system-error-app">Search</Label>
      <Input
        id="system-error-app"
        v-model="model.app"
        placeholder="App contains..."
        autocomplete="off"
      />
    </div>
    <div class="flex flex-col gap-2">
      <Label for="system-error-severity">Severity</Label>
      <Input
        id="system-error-severity"
        v-model="model.severity"
        type="number"
        min="0"
        step="1"
        placeholder="Any"
      />
    </div>
    <div class="flex flex-col gap-2">
      <Label for="system-error-resolved">Resolved</Label>
      <Select v-model="model.resolved">
        <SelectTrigger id="system-error-resolved">
          <SelectValue placeholder="All statuses" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="all">All</SelectItem>
          <SelectItem value="true">Resolved</SelectItem>
          <SelectItem value="false">Unresolved</SelectItem>
        </SelectContent>
      </Select>
    </div>
    <div class="flex flex-col gap-2">
      <Label for="system-error-job">Job ID</Label>
      <Input
        id="system-error-job"
        v-model="model.jobId"
        placeholder="Job UUID"
        autocomplete="off"
      />
    </div>
    <div class="flex flex-col gap-2">
      <Label for="system-error-user">User ID</Label>
      <Input
        id="system-error-user"
        v-model="model.userId"
        placeholder="User UUID"
        autocomplete="off"
      />
    </div>
    <div class="flex items-end">
      <Button
        variant="outline"
        class="w-full md:w-auto"
        :disabled="!hasActiveFilters"
        @click="resetFilters"
      >
        Clear
      </Button>
    </div>
  </div>
</template>
