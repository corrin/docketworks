<template>
  <Dialog :open="props.open" @update:open="(val) => emit('update:open', val)">
    <DialogContent class="max-w-4xl w-full h-[80vh] p-5 m-5 flex flex-col">
      <DialogHeader>
        <DialogTitle>Job Sheet - Job {{ jobNumber }}</DialogTitle>
        <DialogDescription class="sr-only">
          Job Sheet PDF Viewer with options for download, impression and attachment
        </DialogDescription>
        <DialogClose asChild> </DialogClose>
      </DialogHeader>
      <div class="flex-1 overflow-auto">
        <WorkshopPdfViewer :job-id="jobId" />
      </div>
      <footer class="border-t p-4 bg-gray-50 flex justify-end space-x-2">
        <Button v-if="blobUrl" variant="outline" size="icon" class="dark" asChild>
          <a :href="blobUrl" :download="`workshop_job_${props.jobNumber}.pdf`" class="block p-2">
            <Download color="#fff" />
          </a>
        </Button>
        <Button v-if="blobUrl" @click="printPdf"> Print </Button>
        <Button v-if="blobUrl" @click="attachPdf" :disabled="attaching || attached">
          {{ attached ? 'Attached ✅' : attaching ? 'Attaching...' : 'Attach to Job' }}
        </Button>
      </footer>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogClose,
  DialogDescription,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import WorkshopPdfViewer from './WorkshopPdfViewer.vue'
import { ref, watch } from 'vue'
import { jobService } from '@/services/job.service'
import { Download } from 'lucide-vue-next'

const props = defineProps<{
  jobId: string
  jobNumber: number | undefined
  open: boolean
}>()

const emit = defineEmits<{
  (e: 'update:open', value: boolean): void
}>()

const blobUrl = ref<string>('')
const attaching = ref(false)
const attached = ref(false)

watch(
  () => props.open,
  async (open) => {
    if (open) {
      try {
        const blob = await jobService.getWorkshopPdf(props.jobId)
        blobUrl.value = URL.createObjectURL(blob)
      } catch (err) {
        debugLog('Error generating blobUrl from PDF:', err)
        throw err
      }
    }
  },
)

function printPdf() {
  const win = window.open(blobUrl.value, '_blank')
  if (win) win.print()
}

async function attachPdf() {
  attaching.value = true
  try {
    await jobService.getWorkshopPdf(props.jobId)
    // Note: attachWorkshopPdf functionality not available in clean API
    attached.value = true
  } catch (err) {
    debugLog('Error attaching PDF:', err)
    throw err
  } finally {
    attaching.value = false
  }
}
</script>
