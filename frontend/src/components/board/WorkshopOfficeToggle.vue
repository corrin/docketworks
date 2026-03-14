<script setup lang="ts">
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useRoute, useRouter } from 'vue-router'
import { useBoardMode, type BoardMode } from '@/composables/useBoardMode'

const route = useRoute()
const router = useRouter()
const { activeMode, setMode } = useBoardMode()

const handleModeChange = (value: string | number) => {
  const newMode = value as BoardMode
  setMode(newMode)

  // If on a job detail page, redirect to the appropriate view
  const jobIdMatch = route.path.match(/^\/jobs\/([^/]+)(\/workshop)?$/)
  if (jobIdMatch) {
    const jobId = jobIdMatch[1]
    const isWorkshopRoute = !!jobIdMatch[2]

    if (newMode === 'workshop' && !isWorkshopRoute) {
      router.push(`/jobs/${jobId}/workshop`)
    } else if (newMode === 'office' && isWorkshopRoute) {
      router.push(`/jobs/${jobId}`)
    }
  }
}
</script>

<template>
  <Tabs :model-value="activeMode" @update:model-value="handleModeChange">
    <TabsList class="h-8 p-0.5">
      <TabsTrigger value="workshop" class="text-xs px-2 py-1 h-7"> Workshop </TabsTrigger>
      <TabsTrigger value="office" class="text-xs px-2 py-1 h-7"> Office </TabsTrigger>
    </TabsList>
  </Tabs>
</template>
