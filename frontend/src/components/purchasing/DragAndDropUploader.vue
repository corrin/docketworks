<template>
  <div
    class="border-2 border-dashed border-gray-300 rounded-xl p-8 text-center cursor-pointer hover:border-gray-400"
    @click="trigger"
    @drop.prevent="onDrop"
    @dragover.prevent
  >
    <slot>
      <p class="text-sm text-gray-600">
        <span class="font-medium text-indigo-600">Click to upload</span> or drag and drop
      </p>
    </slot>
    <input
      ref="input"
      type="file"
      class="hidden"
      multiple
      accept="application/pdf,image/*"
      @change="handleFiles"
    />
  </div>
</template>
<script setup lang="ts">
import { ref } from 'vue'

const emit = defineEmits<{ files: [FileList] }>()
const input = ref<HTMLInputElement>()

function trigger() {
  input.value?.click()
}

function handleFiles(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files) emit('files', target.files)
  target.value = ''
}

function onDrop(e: DragEvent) {
  if (e.dataTransfer?.files) emit('files', e.dataTransfer.files)
}
</script>
