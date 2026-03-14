<script setup lang="ts">
import { Button } from '@/components/ui/button'
import {
  Drawer,
  DrawerClose,
  DrawerContent,
  DrawerDescription,
  DrawerFooter,
  DrawerHeader,
  DrawerOverlay,
  DrawerTitle,
} from '@/components/ui/drawer'
import { schemas } from '@/api/generated/api'
import type { z } from 'zod'

type JobsListResponse = z.infer<typeof schemas.JobsListResponse>

interface Props {
  open: boolean
  jobSearch: string
  filteredJobs: JobsListResponse['jobs']
}

defineProps<Props>()

const emit = defineEmits<{
  (event: 'update:open', open: boolean): void
  (event: 'update:jobSearch', value: string): void
  (event: 'select', jobId: string): void
}>()
</script>

<template>
  <Drawer :open="open" @update:open="(value) => emit('update:open', value)">
    <DrawerOverlay />
    <DrawerContent
      class="flex !h-[90vh] !max-h-[90vh] min-h-0 flex-col overflow-hidden sm:!h-auto sm:!max-h-[85vh]"
      data-automation-id="WorkshopJobPickerDrawer"
    >
      <div class="mx-auto flex h-full w-full max-w-4xl flex-col min-h-0">
        <DrawerHeader>
          <DrawerTitle class="text-xl font-semibold">Select a job</DrawerTitle>
          <DrawerDescription>Search by job number, name, or client</DrawerDescription>
        </DrawerHeader>
        <div class="drawer-scroll flex-1 overflow-y-auto px-4 pb-4 space-y-3">
          <input
            :value="jobSearch"
            type="text"
            placeholder="Search jobs..."
            class="w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
            data-automation-id="WorkshopJobPickerDrawer-search"
            @input="emit('update:jobSearch', ($event.target as HTMLInputElement).value)"
          />
          <div class="overflow-x-auto rounded-md border">
            <table class="min-w-full text-sm">
              <thead class="bg-muted sticky top-0">
                <tr>
                  <th class="text-left px-3 py-2 font-semibold">Job #</th>
                  <th class="text-left px-3 py-2 font-semibold">Name</th>
                  <th class="text-left px-3 py-2 font-semibold">Client</th>
                  <th class="text-left px-3 py-2 font-semibold">Action</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="job in filteredJobs" :key="job.id" class="border-t hover:bg-muted/50">
                  <td class="px-3 py-2 whitespace-nowrap">#{{ job.job_number }}</td>
                  <td class="px-3 py-2">{{ job.name }}</td>
                  <td class="px-3 py-2">{{ job.client_name || '-' }}</td>
                  <td class="px-3 py-2">
                    <Button
                      size="sm"
                      class="h-8 px-3"
                      :data-automation-id="`WorkshopJobPickerDrawer-select-${job.id}`"
                      @click="emit('select', job.id)"
                    >
                      Select
                    </Button>
                  </td>
                </tr>
                <tr v-if="filteredJobs.length === 0">
                  <td colspan="4" class="px-3 py-4 text-center text-muted-foreground">
                    No jobs found.
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
        <DrawerFooter class="px-4 pb-4">
          <DrawerClose as-child>
            <Button variant="outline" size="sm">Close</Button>
          </DrawerClose>
        </DrawerFooter>
      </div>
    </DrawerContent>
  </Drawer>
</template>
