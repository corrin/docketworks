<template>
  <AppLayout>
    <div class="p-4 md:p-8 flex flex-col gap-4">
      <Card class="rounded-2xl shadow-lg">
        <CardHeader class="border-b">
          <div class="flex items-center gap-2">
            <UploadCloud class="w-6 h-6 text-indigo-600" />
            <h1 class="text-xl font-bold">Upload Supplier Pricing</h1>
          </div>
        </CardHeader>
        <CardContent>
          <DragAndDropUploader @files="upload">
            <p class="text-sm text-gray-600">Drop price file here</p>
          </DragAndDropUploader>
        </CardContent>
      </Card>
    </div>
  </AppLayout>
</template>
<script setup lang="ts">
import { debugLog } from '@/utils/debug'

import AppLayout from '@/components/AppLayout.vue'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { UploadCloud } from 'lucide-vue-next'
import DragAndDropUploader from '@/components/purchasing/DragAndDropUploader.vue'
function upload(files: FileList) {
  debugLog('upload', files)
}
</script>
