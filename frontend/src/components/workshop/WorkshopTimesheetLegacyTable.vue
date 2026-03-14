<script setup lang="ts">
import { schemas } from '@/api/generated/api'
import { AlertTriangle, Pencil, Trash2 } from 'lucide-vue-next'
import { formatHoursDisplay } from '@/utils/string-formatting'
import type { z } from 'zod'

type WorkshopTimesheetEntry = z.infer<typeof schemas.WorkshopTimesheetEntry>

interface Props {
  entries: WorkshopTimesheetEntry[]
  displayRate: (multiplier?: number | null) => string
  safeRateMultiplier: (value: unknown) => number | null
}

defineProps<Props>()

const emit = defineEmits<{
  (event: 'edit', entry: WorkshopTimesheetEntry): void
  (event: 'delete', id: string): void
}>()
</script>

<template>
  <div class="space-y-4 rounded-lg border border-amber-100 bg-amber-50/80 p-4">
    <div class="flex items-start gap-3">
      <div class="rounded-full bg-amber-100 p-2 text-amber-700">
        <AlertTriangle class="h-5 w-5" />
      </div>
      <div class="space-y-1">
        <p class="text-sm font-semibold text-amber-900">Start/end times required</p>
        <p class="text-sm text-amber-800">
          We couldn&apos;t show the calendar because some entries are missing their start or end
          time. Edit each entry to add times, then the timeline will reappear.
        </p>
      </div>
    </div>
    <div class="overflow-auto rounded-lg border bg-white shadow-sm">
      <table class="min-w-full text-sm">
        <thead class="bg-muted/40 text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            <th class="px-3 py-2 text-left font-medium w-[32%]">Job</th>
            <th class="px-3 py-2 text-left font-medium">Details</th>
            <th class="px-3 py-2 text-right font-medium w-[12%]">Hours</th>
            <th class="px-3 py-2 text-left font-medium w-[96px]">Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in entries" :key="entry.id" class="border-t hover:bg-muted/40 align-top">
            <td class="px-3 py-3 text-sm font-medium text-foreground">
              <div class="leading-tight">
                <div class="text-sm font-semibold">
                  #{{ entry.job_number }} &middot; {{ entry.job_name }}
                </div>
                <div class="text-xs text-muted-foreground">
                  {{ entry.client_name || 'No client' }}
                </div>
              </div>
            </td>
            <td class="px-3 py-3">
              <p class="text-sm text-muted-foreground line-clamp-2">
                {{ entry.description || 'No description' }}
              </p>
              <div class="mt-2 flex flex-wrap gap-2 text-xs">
                <span class="rounded-full bg-muted px-2 py-0.5">
                  {{ displayRate(safeRateMultiplier(entry.wage_rate_multiplier)) }}
                </span>
                <span
                  class="rounded-full px-2 py-0.5 font-semibold"
                  :class="
                    entry.is_billable
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-gray-200 text-gray-600'
                  "
                >
                  {{ entry.is_billable ? 'Billable' : 'Non-billable' }}
                </span>
              </div>
            </td>
            <td class="px-3 py-3 text-right font-semibold text-sm whitespace-nowrap">
              {{ formatHoursDisplay(entry.hours) }}
            </td>
            <td class="px-3 py-2">
              <div class="flex items-center gap-2">
                <button
                  class="rounded-md border bg-white p-2 text-muted-foreground hover:text-foreground"
                  @click="emit('edit', entry)"
                >
                  <Pencil class="h-4 w-4" />
                  <span class="sr-only">Edit entry</span>
                </button>
                <button
                  class="rounded-md border bg-white p-2 text-muted-foreground hover:text-destructive"
                  @click="emit('delete', entry.id)"
                >
                  <Trash2 class="h-4 w-4" />
                  <span class="sr-only">Delete entry</span>
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>
