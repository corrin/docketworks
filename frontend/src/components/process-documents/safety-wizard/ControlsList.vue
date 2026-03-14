<template>
  <div class="space-y-3">
    <!-- Current Controls -->
    <div class="space-y-2">
      <div
        v-for="(control, index) in controls"
        :key="index"
        class="flex items-center gap-2 p-2 bg-white border border-gray-200 rounded-md group"
      >
        <Shield class="w-4 h-4 text-green-500 flex-shrink-0" />
        <span class="flex-1 text-sm text-gray-700">{{ control }}</span>
        <Button
          variant="ghost"
          size="sm"
          @click="$emit('remove', index)"
          class="opacity-0 group-hover:opacity-100 transition-opacity h-7 w-7 p-0 text-red-500 hover:text-red-600 hover:bg-red-50"
        >
          <X class="w-4 h-4" />
        </Button>
      </div>
      <div
        v-if="controls.length === 0"
        class="p-4 text-center text-sm text-gray-500 bg-gray-50 rounded-md"
      >
        No control measures added yet.
      </div>
    </div>

    <!-- Suggested Controls -->
    <div v-if="suggestedControls.length > 0" class="space-y-2">
      <p class="text-xs font-medium text-green-600 uppercase tracking-wide">AI Suggestions</p>
      <div
        v-for="(control, index) in suggestedControls"
        :key="index"
        class="flex items-start gap-2 p-2 bg-green-50 border border-green-200 rounded-md"
      >
        <Sparkles class="w-4 h-4 text-green-500 flex-shrink-0 mt-0.5" />
        <span class="flex-1 text-sm text-green-700">{{ control }}</span>
        <Button
          variant="ghost"
          size="sm"
          @click="$emit('accept-suggestion', control)"
          class="h-7 text-green-600 hover:text-green-700 hover:bg-green-100"
        >
          <Plus class="w-4 h-4" />
          Add
        </Button>
      </div>
    </div>

    <!-- Add Custom Control -->
    <div class="flex gap-2">
      <Input v-model="newControl" placeholder="Add a control measure..." class="flex-1" />
      <Button variant="outline" @click="addCustomControl" :disabled="!newControl.trim()">
        <Plus class="w-4 h-4 mr-1" />
        Add
      </Button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Shield, X, Sparkles, Plus } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface Props {
  controls: string[]
  suggestedControls: string[]
}

defineProps<Props>()

const emit = defineEmits<{
  add: [control: string]
  remove: [index: number]
  'accept-suggestion': [control: string]
}>()

const newControl = ref('')

function addCustomControl() {
  if (newControl.value.trim()) {
    emit('add', newControl.value.trim())
    newControl.value = ''
  }
}
</script>
