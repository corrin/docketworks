<script setup lang="ts">
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { CalendarDays, ChevronLeft, ChevronRight } from 'lucide-vue-next'

interface Props {
  formattedDate: string
}

defineProps<Props>()

const emit = defineEmits<{
  (event: 'shift', delta: number): void
}>()
</script>

<template>
  <header class="border-b bg-background/95 backdrop-blur" data-automation-id="WorkshopMyTimeHeader">
    <div
      class="px-4 py-4 sm:px-6 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between"
    >
      <div class="flex items-center gap-2">
        <CalendarDays class="h-5 w-5 text-muted-foreground" />
        <div>
          <p class="text-sm text-muted-foreground">My Time</p>
          <p class="text-lg font-semibold text-foreground">Workshop timesheets</p>
        </div>
      </div>
      <div class="flex items-center gap-2">
        <Button
          variant="ghost"
          size="sm"
          class="h-9"
          data-automation-id="WorkshopMyTimeHeader-previous-day"
          @click="emit('shift', -1)"
        >
          <ChevronLeft class="h-4 w-4 mr-1" />
          Previous day
        </Button>
        <Badge
          variant="outline"
          class="px-3 py-1 text-sm"
          data-automation-id="WorkshopMyTimeHeader-date"
        >
          {{ formattedDate }}
        </Badge>
        <Button
          variant="ghost"
          size="sm"
          class="h-9"
          data-automation-id="WorkshopMyTimeHeader-next-day"
          @click="emit('shift', 1)"
        >
          Next day
          <ChevronRight class="h-4 w-4 ml-1" />
        </Button>
      </div>
    </div>
  </header>
</template>
