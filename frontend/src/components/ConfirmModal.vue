<template>
  <Dialog :open="true" @update:open="handleClose">
    <DialogContent class="max-w-md animate-in fade-in-0 zoom-in-95">
      <DialogHeader>
        <DialogTitle>{{ title }}</DialogTitle>
        <DialogDescription>{{ message }}</DialogDescription>
      </DialogHeader>
      <DialogFooter class="flex gap-2 justify-end">
        <Button variant="ghost" @click="handleClose">Cancel</Button>
        <Button variant="destructive" @click="handleConfirm">Delete</Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import Dialog from '@/components/ui/dialog/Dialog.vue'
import DialogContent from '@/components/ui/dialog/DialogContent.vue'
import DialogHeader from '@/components/ui/dialog/DialogHeader.vue'
import DialogTitle from '@/components/ui/dialog/DialogTitle.vue'
import DialogDescription from '@/components/ui/dialog/DialogDescription.vue'
import DialogFooter from '@/components/ui/dialog/DialogFooter.vue'
import Button from '@/components/ui/button/Button.vue'
const { title, message } = defineProps<{
  title: string
  message: string
}>()
const emit = defineEmits(['close', 'confirm'])
function handleClose() {
  emit('close')
}
function handleConfirm() {
  emit('confirm')
}
</script>

<style scoped>
.animate-in {
  animation: fadeInZoom 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
@keyframes fadeInZoom {
  from {
    opacity: 0;
    transform: scale(0.95);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}
</style>
