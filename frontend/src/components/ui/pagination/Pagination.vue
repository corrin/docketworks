<!-- eslint-disable vue/multi-word-component-names -->
<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { ChevronLeft, ChevronRight } from 'lucide-vue-next'
import { computed } from 'vue'

const props = defineProps<{ page: number; total: number }>()
const emit = defineEmits(['update:page'])

const MAX_VISIBLE = 10

const pages = computed(() => {
  if (props.total < 1) return [1]
  if (props.total <= MAX_VISIBLE) {
    return Array.from({ length: props.total }, (_, i) => i + 1)
  }

  const halfWindow = Math.floor(MAX_VISIBLE / 2)
  const maxStart = props.total - MAX_VISIBLE + 1
  const candidateStart = props.page - halfWindow
  const start = Math.max(1, Math.min(candidateStart, maxStart))
  const last = Math.min(start + MAX_VISIBLE - 1, props.total)
  const length = last - start + 1

  return Array.from({ length }, (_, i) => start + i)
})
function select(p: number) {
  if (p !== props.page) emit('update:page', p)
}
function prev() {
  if (props.page > 1) emit('update:page', props.page - 1)
}
function next() {
  if (props.page < props.total) emit('update:page', props.page + 1)
}
</script>

<template>
  <div class="flex items-center justify-center gap-1 py-2">
    <Button variant="ghost" size="sm" @click="prev" :disabled="props.page <= 1 || props.total < 2">
      <ChevronLeft class="w-4 h-4" />
    </Button>
    <Button
      v-for="p in pages"
      :key="p"
      variant="ghost"
      size="sm"
      @click="select(p)"
      :class="p === props.page ? 'bg-primary text-white' : ''"
    >
      {{ p }}
    </Button>
    <Button
      variant="ghost"
      size="sm"
      @click="next"
      :disabled="props.page >= props.total || props.total < 2"
    >
      <ChevronRight class="w-4 h-4" />
    </Button>
  </div>
</template>
