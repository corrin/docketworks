<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { ClipboardList, Plus } from 'lucide-vue-next'

defineEmits<{
  (e: 'select-job'): void
}>()
</script>

<template>
  <div class="text-center py-16 px-6 bg-gray-50 rounded-xl border-2 border-dashed border-gray-300">
    <ClipboardList class="h-16 w-16 mx-auto text-gray-400 mb-4" />
    <h2 class="text-2xl font-bold text-gray-700 mb-2">No Job Selected</h2>
    <p class="text-gray-500 mb-6 max-w-md mx-auto">
      Select a job to start working on. You'll see job details and can quickly access the job page.
    </p>
    <Button size="lg" @click="$emit('select-job')">
      <Plus class="h-5 w-5" />
      Select a Job
    </Button>
  </div>
</template>
