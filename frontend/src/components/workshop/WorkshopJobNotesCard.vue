<script setup lang="ts">
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { NotebookText } from 'lucide-vue-next'

interface Props {
  notesHtml: string
}

defineProps<Props>()
</script>

<template>
  <Card class="lg:col-span-12">
    <CardHeader>
      <CardTitle class="flex items-center gap-2">
        <NotebookText class="h-5 w-5" />
        Notes
      </CardTitle>
    </CardHeader>
    <CardContent>
      <div
        class="rounded-md border bg-background px-3 py-3 text-base leading-relaxed workshop-richtext"
      >
        <div v-if="notesHtml" v-html="notesHtml" />
        <span v-else>&mdash;</span>
      </div>
    </CardContent>
  </Card>
</template>

<style scoped>
.workshop-richtext :deep(p) {
  margin: 0 0 0.75rem;
}
.workshop-richtext :deep(p:last-child) {
  margin-bottom: 0;
}
.workshop-richtext :deep(ul),
.workshop-richtext :deep(ol) {
  padding-left: 1.25rem;
  margin: 0.5rem 0;
}
.workshop-richtext :deep(li) {
  margin: 0.25rem 0;
}
.workshop-richtext :deep(a) {
  text-decoration: underline;
}
</style>
