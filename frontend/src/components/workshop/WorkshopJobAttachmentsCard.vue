<script setup lang="ts">
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { schemas } from '@/api/generated/api'
import { ArrowRightToLine, Download, Eye, EyeOff, FileText } from 'lucide-vue-next'
import { nextTick } from 'vue'
import type { z } from 'zod'

type JobFile = z.infer<typeof schemas.JobFile>

interface Props {
  attachments: JobFile[]
  attachmentsLoading: boolean
  attachmentsError: boolean
  expandedAttachmentIds: Set<string>
  previewLoading: Set<string>
  previewErrors: Set<string>
  formatSize: (bytes?: number | null) => string
  formatDateShort: (dateString?: string | null) => string
  downloadAttachment: (file: JobFile) => void
  toggleAttachment: (file: JobFile) => void
  ensurePreviewUrl: (file: JobFile) => Promise<void> | void
  previewUrlFor: (file: JobFile) => string | undefined
  openPdfInNewTab: (file: JobFile) => void
  isImage: (file: JobFile) => boolean
  isPdf: (file: JobFile) => boolean
}

const props = defineProps<Props>()

async function handleTogglePreview(file: JobFile) {
  props.toggleAttachment(file)
  await nextTick()
  if (props.expandedAttachmentIds.has(String(file.id))) {
    await props.ensurePreviewUrl(file)
  }
}
</script>

<template>
  <Card class="lg:col-span-12">
    <CardHeader class="flex items-center justify-between">
      <CardTitle class="flex items-center gap-2">
        <FileText class="h-5 w-5" />
        Attachments
      </CardTitle>
    </CardHeader>
    <CardContent>
      <div v-if="attachmentsLoading" class="space-y-3">
        <Skeleton class="h-10 w-full" />
        <Skeleton class="h-10 w-full" />
      </div>
      <div v-else-if="attachmentsError" class="text-sm text-muted-foreground">
        Failed to load attachments. Please refresh.
      </div>
      <div v-else-if="attachments.length === 0" class="text-sm text-muted-foreground">
        No attachments uploaded.
      </div>
      <div v-else class="divide-y divide-border">
        <div v-for="file in attachments" :key="file.id" class="flex flex-col gap-2 py-3">
          <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
            <div class="min-w-0 flex-1">
              <div class="text-sm font-medium text-foreground truncate">
                {{ file.filename }}
              </div>
              <div class="text-xs text-muted-foreground flex flex-wrap gap-2">
                <span>{{ formatSize(file.size) }}</span>
                <span class="hidden sm:inline">&middot;</span>
                <span>{{ formatDateShort(file.uploaded_at) }}</span>
                <span class="text-muted-foreground">&middot; View only</span>
              </div>
            </div>
            <div class="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                class="h-9 w-30 justify-center"
                @click="downloadAttachment(file)"
              >
                <Download class="h-4 w-4 mr-1" />
                Download
              </Button>
              <Button
                v-if="isImage(file) || isPdf(file)"
                variant="secondary"
                size="sm"
                class="h-9 w-25 justify-center px-3"
                @click="handleTogglePreview(file)"
              >
                <component
                  :is="expandedAttachmentIds.has(String(file.id)) ? EyeOff : Eye"
                  class="h-4 w-4 mr-1"
                />
                {{ expandedAttachmentIds.has(String(file.id)) ? 'Hide' : 'Show' }}
              </Button>
            </div>
          </div>

          <div
            v-if="expandedAttachmentIds.has(String(file.id)) && (isImage(file) || isPdf(file))"
            class="rounded-md border bg-muted/30 p-3"
          >
            <div v-if="previewLoading.has(String(file.id))" class="text-sm text-muted-foreground">
              Loading preview...
            </div>
            <div v-else-if="previewErrors.has(String(file.id))" class="text-sm text-destructive">
              Preview unavailable for this file.
            </div>
            <template v-else>
              <div v-if="isImage(file)" class="w-full overflow-auto">
                <img
                  :src="previewUrlFor(file) || file.thumbnail_url || file.download_url"
                  :alt="file.filename"
                  class="w-full max-w-full rounded-md object-contain"
                />
              </div>
              <div v-else-if="isPdf(file)" class="w-full space-y-2">
                <object
                  v-if="previewUrlFor(file)"
                  :data="previewUrlFor(file)"
                  type="application/pdf"
                  class="w-full min-h-[70vh] sm:min-h-[520px] max-h-[80vh] rounded-md border overflow-auto"
                >
                  <p class="text-sm text-muted-foreground">
                    PDF preview is not supported in this browser.
                  </p>
                </object>
                <div v-else class="text-sm text-muted-foreground">PDF unavailable.</div>
                <div class="flex justify-end">
                  <Button
                    variant="outline"
                    size="sm"
                    class="h-8 px-3"
                    @click="() => openPdfInNewTab(file)"
                  >
                    <ArrowRightToLine class="h-4 w-4 mr-1" />
                    Open full PDF
                  </Button>
                </div>
              </div>
            </template>
          </div>
        </div>
      </div>
    </CardContent>
  </Card>
</template>
