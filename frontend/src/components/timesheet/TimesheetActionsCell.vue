<script setup lang="ts">
import { Check, Trash2 } from 'lucide-vue-next'

defineProps<{
  approved: boolean
  canApprove: boolean
  onApprove?: () => void
  onDelete?: () => void
}>()
</script>

<template>
  <div class="flex items-center justify-center gap-3 min-h-[28px]">
    <button
      v-if="canApprove && !approved"
      class="h-7 w-7 rounded-md bg-emerald-500 text-white flex items-center justify-center shadow-sm"
      type="button"
      title="Approve"
      @click="onApprove?.()"
    >
      <Check class="h-3.5 w-3.5" />
    </button>
    <button
      class="h-7 w-7 rounded-md bg-transparent text-slate-500 flex items-center justify-center"
      type="button"
      title="Delete"
      @click="onDelete?.()"
    >
      <Trash2 class="h-4 w-4" />
    </button>
  </div>
</template>
