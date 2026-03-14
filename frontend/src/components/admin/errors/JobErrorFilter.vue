<script setup lang="ts">
import { computed } from 'vue'
import { useVModel } from '@vueuse/core'
import Input from '@/components/ui/input/Input.vue'
import Label from '@/components/ui/label/Label.vue'
import { Button } from '@/components/ui/button'
import type { JobErrorFilterState } from '@/types/errorFilters'

const defaultState: JobErrorFilterState = {
  jobId: '',
}

const props = defineProps<{ modelValue: JobErrorFilterState }>()
const emit = defineEmits<{ 'update:modelValue': [JobErrorFilterState] }>()

const model = useVModel(props, 'modelValue', emit)

const hasFilters = computed(() => !!model.value.jobId.trim())

function resetFilters() {
  model.value = { ...defaultState }
}
</script>

<template>
  <div class="flex flex-wrap items-end gap-4">
    <div class="flex flex-col gap-2 min-w-[220px]">
      <Label for="job-error-job-id">Job ID</Label>
      <Input
        id="job-error-job-id"
        v-model="model.jobId"
        placeholder="UUID or leave blank for all"
        autocomplete="off"
      />
    </div>
    <Button
      variant="outline"
      class="w-full sm:w-auto"
      :disabled="!hasFilters"
      @click="resetFilters"
    >
      Clear
    </Button>
  </div>
</template>
