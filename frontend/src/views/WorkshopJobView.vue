<script setup lang="ts">
import AppLayout from '@/components/AppLayout.vue'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import WorkshopMaterialsUsedTable from '@/components/workshop/WorkshopMaterialsUsedTable.vue'
import WorkshopTimeUsedTable from '@/components/workshop/WorkshopTimeUsedTable.vue'
import WorkshopJobHeader from '@/components/workshop/WorkshopJobHeader.vue'
import WorkshopJobKeyInfoCard from '@/components/workshop/WorkshopJobKeyInfoCard.vue'
import WorkshopJobSummaryCard from '@/components/workshop/WorkshopJobSummaryCard.vue'
import WorkshopJobDescriptionCard from '@/components/workshop/WorkshopJobDescriptionCard.vue'
import WorkshopJobNotesCard from '@/components/workshop/WorkshopJobNotesCard.vue'
import WorkshopJobAttachmentsCard from '@/components/workshop/WorkshopJobAttachmentsCard.vue'
import { useWorkshopJob } from '@/composables/useWorkshopJob'
import { useJobAttachments } from '@/composables/useJobAttachments'

const route = useRoute()
const router = useRouter()

const jobId = computed(() => route.params.id as string)
const { job, loading, notesHtml, speedQuality, workshopTime, workshopTimeDisplay, formatDate } =
  useWorkshopJob(jobId)

function navigateBack() {
  if (window.history.length > 1) {
    router.back()
    return
  }
  router.push({ name: 'kanban' })
}
const {
  attachments,
  attachmentsLoading,
  attachmentsError,
  expandedAttachmentIds,
  previewLoading,
  previewErrors,
  formatSize,
  formatDateShort,
  downloadAttachment,
  isImage,
  isPdf,
  toggleAttachment,
  ensurePreviewUrl,
  previewUrlFor,
  openPdfInNewTab,
} = useJobAttachments(jobId)
</script>

<template>
  <AppLayout>
    <div class="flex flex-col h-full min-h-0 bg-muted/10">
      <WorkshopJobHeader
        :job="job"
        :speed-quality="speedQuality"
        :job-id="jobId"
        @back="navigateBack"
      />

      <main class="flex-1 min-h-0 overflow-y-auto px-4 py-4 sm:px-6">
        <div v-if="loading" class="grid gap-4 lg:gap-6 lg:grid-cols-12">
          <Card class="lg:col-span-5">
            <CardHeader>
              <CardTitle><Skeleton class="h-5 w-28" /></CardTitle>
            </CardHeader>
            <CardContent class="space-y-3">
              <Skeleton class="h-4 w-full" />
              <Skeleton class="h-4 w-5/6" />
              <Skeleton class="h-4 w-4/6" />
              <Skeleton class="h-4 w-3/6" />
            </CardContent>
          </Card>

          <Card class="lg:col-span-7">
            <CardHeader>
              <CardTitle><Skeleton class="h-5 w-24" /></CardTitle>
            </CardHeader>
            <CardContent class="grid grid-cols-2 gap-4 sm:grid-cols-3">
              <Skeleton class="h-20 w-full" />
              <Skeleton class="h-20 w-full" />
              <Skeleton class="h-20 w-full" />
            </CardContent>
          </Card>

          <Card class="lg:col-span-12">
            <CardHeader>
              <CardTitle><Skeleton class="h-5 w-24" /></CardTitle>
            </CardHeader>
            <CardContent class="space-y-2">
              <Skeleton class="h-4 w-full" />
              <Skeleton class="h-4 w-11/12" />
              <Skeleton class="h-4 w-10/12" />
            </CardContent>
          </Card>
        </div>

        <div v-else-if="!job" class="max-w-3xl mx-auto">
          <Card>
            <CardHeader>
              <CardTitle>Job not found</CardTitle>
            </CardHeader>
            <CardContent class="text-sm text-muted-foreground">
              This job could not be loaded. Go back and try again.
            </CardContent>
          </Card>
        </div>

        <div v-else class="grid gap-4 lg:gap-6 lg:grid-cols-12">
          <WorkshopJobKeyInfoCard :job="job" :format-date="formatDate" />
          <WorkshopJobSummaryCard
            :job="job"
            :workshop-time-display="workshopTimeDisplay"
            :workshop-time-source="workshopTime.source"
            :speed-quality-label="speedQuality?.label ?? null"
          />
          <WorkshopJobDescriptionCard :job="job" />
          <WorkshopJobNotesCard :notes-html="notesHtml" />

          <div class="lg:col-span-12">
            <WorkshopMaterialsUsedTable :job-id="jobId" />
          </div>

          <div class="lg:col-span-12">
            <WorkshopTimeUsedTable :job-id="jobId" :workshop-hours="workshopTime.hours" />
          </div>

          <WorkshopJobAttachmentsCard
            :attachments="attachments"
            :attachments-loading="attachmentsLoading"
            :attachments-error="attachmentsError"
            :expanded-attachment-ids="expandedAttachmentIds"
            :preview-loading="previewLoading"
            :preview-errors="previewErrors"
            :format-size="formatSize"
            :format-date-short="formatDateShort"
            :download-attachment="downloadAttachment"
            :toggle-attachment="toggleAttachment"
            :ensure-preview-url="ensurePreviewUrl"
            :preview-url-for="previewUrlFor"
            :open-pdf-in-new-tab="openPdfInNewTab"
            :is-image="isImage"
            :is-pdf="isPdf"
          />
        </div>
      </main>
    </div>
  </AppLayout>
</template>
