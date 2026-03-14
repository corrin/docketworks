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
import { Ban, Save, Shuffle, Trash2 } from 'lucide-vue-next'
import { computed } from 'vue'
import { formatHoursDisplay } from '@/utils/string-formatting'

interface FormState {
  jobId: string
  startTime: string
  endTime: string
  description: string
  isBillable: boolean
  rateMultiplier: string
}

interface Props {
  open: boolean
  editingEntryId: string | null
  formState: FormState
  formDurationHours: number
  selectedDateLabel: string
  selectedJobLabel: string | null
  isSubmitting: boolean
  isDayLoading: boolean
  onOpenJobPicker: () => void
  onDeleteEntry: () => void
  onSubmit: () => void
  onResetForm: () => void
  onSetRangeNow: () => void
  onAdjustRangeBy: (delta: number) => void
  onFillGap: () => void
  onResetRange: () => void
}

const props = defineProps<Props>()

const emit = defineEmits<{
  (event: 'update:open', open: boolean): void
  (event: 'update:formState', value: Partial<FormState>): void
}>()

function handleOpenChange(open: boolean) {
  emit('update:open', open)
  if (!open) {
    props.onResetForm()
  }
}

function updateFormState(value: Partial<FormState>) {
  emit('update:formState', value)
}

const startTime = computed({
  get: () => props.formState.startTime,
  set: (value) => updateFormState({ startTime: value }),
})

const endTime = computed({
  get: () => props.formState.endTime,
  set: (value) => updateFormState({ endTime: value }),
})

const description = computed({
  get: () => props.formState.description,
  set: (value) => updateFormState({ description: value }),
})

const rateMultiplier = computed({
  get: () => props.formState.rateMultiplier,
  set: (value) => updateFormState({ rateMultiplier: value }),
})

const isBillable = computed({
  get: () => props.formState.isBillable,
  set: (value) => updateFormState({ isBillable: value }),
})
</script>

<template>
  <Drawer :open="open" @update:open="handleOpenChange">
    <DrawerOverlay />
    <DrawerContent
      class="flex !h-[90vh] !max-h-[90vh] min-h-0 flex-col overflow-hidden sm:!h-auto sm:!max-h-[85vh]"
      data-automation-id="WorkshopTimesheetEntryDrawer"
    >
      <div class="mx-auto flex h-full w-full max-w-3xl flex-col min-h-0">
        <DrawerHeader>
          <DrawerTitle class="text-xl font-semibold">
            {{ editingEntryId ? 'Edit entry' : 'Add entry' }}
          </DrawerTitle>
          <DrawerDescription>
            Quickly log workshop time for {{ selectedDateLabel }}
          </DrawerDescription>
        </DrawerHeader>
        <div class="drawer-scroll flex-1 overflow-y-auto px-4 pb-4">
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 items-end">
            <div class="text-sm font-medium text-foreground flex flex-col gap-1 sm:col-span-2">
              <span>Job</span>
              <button
                class="rounded-md border px-3 h-[44px] text-left text-sm bg-muted/40 hover:bg-muted/70 transition-colors flex items-center justify-between"
                data-automation-id="WorkshopTimesheetEntryDrawer-job-picker"
                @click="onOpenJobPicker"
              >
                <span class="truncate">
                  <template v-if="formState.jobId && selectedJobLabel">
                    {{ selectedJobLabel }}
                  </template>
                  <span v-else class="text-muted-foreground">Tap to select a job</span>
                </span>
                <Shuffle class="h-4 w-4 text-muted-foreground flex-shrink-0 ml-2" />
              </button>
            </div>
            <label class="text-sm font-medium text-foreground flex flex-col gap-1">
              Start time
              <input
                v-model="startTime"
                type="time"
                class="mt-1 w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                data-automation-id="WorkshopTimesheetEntryDrawer-start-time"
              />
            </label>
            <label class="text-sm font-medium text-foreground flex flex-col gap-1">
              End time
              <input
                v-model="endTime"
                type="time"
                class="mt-1 w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                data-automation-id="WorkshopTimesheetEntryDrawer-end-time"
              />
            </label>
            <div
              class="sm:col-span-2 flex flex-wrap items-center gap-3 text-sm text-muted-foreground"
            >
              <div>
                Duration:
                <span class="font-semibold text-foreground">
                  {{ formatHoursDisplay(formDurationHours) }}
                </span>
              </div>
              <div class="flex flex-wrap gap-2 text-xs">
                <button class="rounded-full border px-3 py-1" type="button" @click="onSetRangeNow">
                  Now
                </button>
                <button
                  class="rounded-full border px-3 py-1"
                  type="button"
                  @click="onAdjustRangeBy(-5)"
                >
                  -5m
                </button>
                <button
                  class="rounded-full border px-3 py-1"
                  type="button"
                  @click="onAdjustRangeBy(5)"
                >
                  +5m
                </button>
                <button
                  class="rounded-full border px-3 py-1"
                  type="button"
                  @click="onAdjustRangeBy(15)"
                >
                  +15m
                </button>
                <button
                  class="rounded-full border px-3 py-1"
                  type="button"
                  @click="onAdjustRangeBy(30)"
                >
                  +30m
                </button>
                <button class="rounded-full border px-3 py-1" type="button" @click="onFillGap">
                  Fill gap
                </button>
                <button class="rounded-full border px-3 py-1" type="button" @click="onResetRange">
                  Reset
                </button>
              </div>
            </div>
            <label class="text-sm font-medium text-foreground flex flex-col gap-1">
              Rate multiplier
              <select
                v-model="rateMultiplier"
                class="w-full rounded-md border px-3 h-[44px] text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                data-automation-id="WorkshopTimesheetEntryDrawer-rate"
              >
                <option value="Ord">Ord</option>
                <option value="1.5">1.5</option>
                <option value="2.0">2.0</option>
              </select>
            </label>
            <label class="text-sm font-medium text-foreground flex flex-col gap-1">
              <span>Billable</span>
              <div class="flex items-center gap-2 h-[44px]">
                <input
                  type="checkbox"
                  class="h-4 w-4 accent-primary"
                  data-automation-id="WorkshopTimesheetEntryDrawer-billable"
                  v-model="isBillable"
                />
                <span>Billable</span>
              </div>
            </label>
            <label class="text-sm font-medium text-foreground sm:col-span-2">
              Description
              <textarea
                v-model="description"
                rows="3"
                class="mt-1 w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary"
                placeholder="What was done"
                data-automation-id="WorkshopTimesheetEntryDrawer-description"
              />
            </label>
          </div>
        </div>
        <DrawerFooter class="px-4 pb-4">
          <div class="flex w-full flex-wrap items-center justify-between gap-3">
            <Button
              v-if="editingEntryId"
              variant="destructive"
              size="sm"
              class="h-9"
              :disabled="isSubmitting || isDayLoading"
              data-automation-id="WorkshopTimesheetEntryDrawer-delete"
              @click="onDeleteEntry"
            >
              <Trash2 class="mr-2 h-4 w-4" />
              Delete
            </Button>
            <div class="ml-auto flex items-center gap-2">
              <DrawerClose as-child>
                <Button
                  variant="outline"
                  size="sm"
                  class="h-9"
                  data-automation-id="WorkshopTimesheetEntryDrawer-cancel"
                  @click="onResetForm"
                >
                  <Ban class="mr-2 h-4 w-4" />
                  Cancel
                </Button>
              </DrawerClose>
              <Button
                size="sm"
                class="h-9"
                :disabled="isSubmitting || isDayLoading"
                data-automation-id="WorkshopTimesheetEntryDrawer-submit"
                @click="onSubmit"
              >
                <Save class="mr-2 h-4 w-4" />
                {{ editingEntryId ? 'Update entry' : 'Save entry' }}
              </Button>
            </div>
          </div>
        </DrawerFooter>
      </div>
    </DrawerContent>
  </Drawer>
</template>
