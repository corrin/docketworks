<template>
  <div class="space-y-3">
    <!-- Current Hazards -->
    <div class="space-y-2">
      <div
        v-for="(hazard, index) in hazards"
        :key="index"
        class="flex items-center gap-2 p-2 bg-white border border-gray-200 rounded-md group"
      >
        <AlertTriangle class="w-4 h-4 text-amber-500 flex-shrink-0" />
        <span class="flex-1 text-sm text-gray-700">{{ hazard }}</span>
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
        v-if="hazards.length === 0"
        class="p-4 text-center text-sm text-gray-500 bg-gray-50 rounded-md"
      >
        No hazards identified yet. Click "Generate Hazards" to get AI suggestions.
      </div>
    </div>

    <!-- Suggested Hazards -->
    <div v-if="suggestedHazards.length > 0" class="space-y-2">
      <p class="text-xs font-medium text-green-600 uppercase tracking-wide">AI Suggestions</p>
      <div
        v-for="hazard in suggestedHazards"
        :key="hazard"
        class="flex items-center gap-2 p-2 bg-green-50 border border-green-200 rounded-md"
      >
        <Sparkles class="w-4 h-4 text-green-500 flex-shrink-0" />
        <span class="flex-1 text-sm text-green-700">{{ hazard }}</span>
        <Button
          variant="ghost"
          size="sm"
          @click="$emit('accept-suggestion', hazard)"
          class="h-7 text-green-600 hover:text-green-700 hover:bg-green-100"
        >
          <Plus class="w-4 h-4" />
          Add
        </Button>
      </div>
    </div>

    <!-- Add Custom Hazard -->
    <div class="flex gap-2">
      <Input
        v-model="newHazard"
        placeholder="Add a custom hazard..."
        class="flex-1"
        @keyup.enter="addCustomHazard"
      />
      <Button variant="outline" @click="addCustomHazard" :disabled="!newHazard.trim()">
        <Plus class="w-4 h-4 mr-1" />
        Add
      </Button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { AlertTriangle, X, Sparkles, Plus } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface Props {
  hazards: string[]
  suggestedHazards: string[]
}

defineProps<Props>()

const emit = defineEmits<{
  add: [hazard: string]
  remove: [index: number]
  'accept-suggestion': [hazard: string]
}>()

const newHazard = ref('')

function addCustomHazard() {
  if (newHazard.value.trim()) {
    emit('add', newHazard.value.trim())
    newHazard.value = ''
  }
}
</script>
