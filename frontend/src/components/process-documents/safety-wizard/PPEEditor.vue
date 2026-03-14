<template>
  <div class="space-y-3">
    <!-- Current PPE Items -->
    <div class="flex flex-wrap gap-2">
      <div
        v-for="(item, index) in ppeRequirements"
        :key="index"
        class="flex items-center gap-1 px-3 py-1.5 bg-blue-100 text-blue-700 rounded-full text-sm group"
      >
        <HardHat class="w-4 h-4" />
        <span>{{ item }}</span>
        <Button
          variant="ghost"
          size="sm"
          @click="$emit('remove', index)"
          class="h-5 w-5 p-0 ml-1 opacity-0 group-hover:opacity-100 transition-opacity text-blue-500 hover:text-blue-700 hover:bg-blue-200 rounded-full"
        >
          <X class="w-3 h-3" />
        </Button>
      </div>

      <div
        v-if="ppeRequirements.length === 0"
        class="p-4 w-full text-center text-sm text-gray-500 bg-gray-50 rounded-md"
      >
        No PPE requirements specified yet.
      </div>
    </div>

    <!-- Suggested PPE -->
    <div v-if="suggestedPpe.length > 0" class="space-y-2">
      <p class="text-xs font-medium text-green-600 uppercase tracking-wide">AI Suggestions</p>
      <div class="flex flex-wrap gap-2">
        <div
          v-for="item in suggestedPpe"
          :key="item"
          class="flex items-center gap-1 px-3 py-1.5 bg-green-100 text-green-700 rounded-full text-sm cursor-pointer hover:bg-green-200 transition-colors"
          @click="$emit('accept-suggestion', item)"
        >
          <Sparkles class="w-4 h-4" />
          <span>{{ item }}</span>
          <Plus class="w-4 h-4 ml-1" />
        </div>
      </div>
    </div>

    <!-- Add Custom PPE -->
    <div class="flex gap-2">
      <Input
        v-model="newItem"
        placeholder="Add PPE item (e.g., Safety glasses, Hard hat)..."
        class="flex-1"
        @keyup.enter="addCustomItem"
      />
      <Button variant="outline" @click="addCustomItem" :disabled="!newItem.trim()">
        <Plus class="w-4 h-4 mr-1" />
        Add
      </Button>
    </div>

    <!-- Common PPE Quick Add -->
    <div class="space-y-2">
      <p class="text-xs font-medium text-gray-500">Quick Add Common PPE</p>
      <div class="flex flex-wrap gap-1">
        <Button
          v-for="item in commonPPE.filter((p) => !ppeRequirements.includes(p))"
          :key="item"
          variant="outline"
          size="sm"
          @click="$emit('add', item)"
          class="h-7 text-xs"
        >
          {{ item }}
        </Button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { HardHat, X, Sparkles, Plus } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface Props {
  ppeRequirements: string[]
  suggestedPpe: string[]
}

defineProps<Props>()

const emit = defineEmits<{
  add: [item: string]
  remove: [index: number]
  'accept-suggestion': [item: string]
}>()

const newItem = ref('')

const commonPPE = [
  'Safety glasses',
  'Hard hat',
  'Steel-capped boots',
  'High-visibility vest',
  'Hearing protection',
  'Gloves',
  'Dust mask',
  'Face shield',
  'Safety harness',
  'Welding helmet',
]

function addCustomItem() {
  if (newItem.value.trim()) {
    emit('add', newItem.value.trim())
    newItem.value = ''
  }
}
</script>
