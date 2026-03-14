<template>
  <div class="border border-gray-200 rounded-lg overflow-hidden">
    <div class="bg-gray-50 px-4 py-2 border-b border-gray-200 flex items-center justify-between">
      <h4 class="text-sm font-medium text-gray-700">{{ title }}</h4>
      <Button
        v-if="!improvedContent"
        variant="outline"
        size="sm"
        @click="emit('generate')"
        :disabled="isGenerating"
        class="gap-1"
      >
        <Loader2 v-if="isGenerating" class="w-4 h-4 animate-spin" />
        <Sparkles v-else class="w-4 h-4" />
        Improve with AI
      </Button>
    </div>

    <div class="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-gray-200">
      <!-- Original / Current -->
      <div class="p-4">
        <div class="flex items-center gap-2 mb-2">
          <span class="text-xs font-medium text-gray-500 uppercase tracking-wide">
            {{ improvedContent ? 'Original' : 'Current' }}
          </span>
        </div>
        <Textarea
          :model-value="originalContent"
          @update:model-value="handleContentUpdate"
          :disabled="!!improvedContent"
          :rows="6"
          class="w-full text-sm"
        />
      </div>

      <!-- Improved (only shown when available) -->
      <div v-if="improvedContent" class="p-4 bg-green-50/50">
        <div class="flex items-center justify-between mb-2">
          <span class="text-xs font-medium text-green-600 uppercase tracking-wide">
            AI Improved
          </span>
          <div class="flex gap-2">
            <Button variant="ghost" size="sm" @click="emit('reject')" class="text-red-600 h-7">
              <X class="w-4 h-4" />
            </Button>
            <Button variant="ghost" size="sm" @click="emit('accept')" class="text-green-600 h-7">
              <Check class="w-4 h-4" />
            </Button>
          </div>
        </div>
        <div class="p-3 bg-white border border-green-200 rounded-md text-sm whitespace-pre-wrap">
          {{ improvedContent }}
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { Sparkles, Loader2, Check, X } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'

interface Props {
  title: string
  originalContent: string
  improvedContent?: string
  isGenerating?: boolean
}

defineProps<Props>()

const emit = defineEmits<{
  generate: []
  accept: []
  reject: []
  'update:content': [value: string]
}>()

function handleContentUpdate(value: string | number) {
  emit('update:content', String(value))
}
</script>
