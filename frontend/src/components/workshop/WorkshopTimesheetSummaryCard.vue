<script setup lang="ts">
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { AlertTriangle, CalendarDays, Plus, RefreshCcw } from 'lucide-vue-next'
import { formatHoursDisplay } from '@/utils/string-formatting'

interface Props {
  formattedDate: string
  overBudgetJobsCount: number
  overBudgetTooltip: string
  selectedDaySummary: { jobs: number; hours: number }
  isDayLoading: boolean
}

defineProps<Props>()

const emit = defineEmits<{
  (event: 'refresh'): void
  (event: 'add'): void
}>()
</script>

<template>
  <Card class="h-auto">
    <CardHeader class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
      <div>
        <CardTitle class="flex items-center gap-2">
          <CalendarDays class="h-5 w-5" />
          {{ formattedDate }}
          <Badge
            v-if="overBudgetJobsCount"
            variant="destructive"
            class="flex items-center gap-1"
            :title="overBudgetTooltip"
          >
            <AlertTriangle class="h-4 w-4" />
            Over hours
          </Badge>
        </CardTitle>
        <p class="text-sm text-muted-foreground">
          {{ formatHoursDisplay(selectedDaySummary.hours) }} &middot;
          {{ selectedDaySummary.jobs }} jobs
        </p>
      </div>
      <div class="flex items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          class="h-9"
          data-automation-id="WorkshopTimesheetSummaryCard-refresh"
          :disabled="isDayLoading"
          @click="emit('refresh')"
        >
          <RefreshCcw class="h-4 w-4 mr-1" />
          Refresh day
        </Button>
        <Button
          size="sm"
          class="h-9"
          data-automation-id="WorkshopTimesheetSummaryCard-add"
          @click="emit('add')"
        >
          <Plus class="h-4 w-4 mr-1" />
          Add entry
        </Button>
      </div>
    </CardHeader>
    <CardContent class="min-h-[360px] sm:min-h-[420px]">
      <slot />
    </CardContent>
  </Card>
</template>
