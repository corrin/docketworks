<template>
  <Dialog :open="isOpen" @update:open="handleClose">
    <DialogContent class="max-w-5xl max-h-[90vh] overflow-hidden flex flex-col">
      <DialogHeader>
        <DialogTitle class="flex items-center gap-2">
          <Sparkles class="w-5 h-5 text-blue-500" />
          AI-Assisted Document Editor
        </DialogTitle>
        <DialogDescription>
          Step {{ currentStepIndex + 1 }} of {{ WIZARD_STEPS.length }}:
          {{ stepLabels[currentStep] }}
        </DialogDescription>
      </DialogHeader>

      <!-- Progress Bar -->
      <div class="flex-shrink-0 px-1">
        <div class="flex gap-1">
          <div
            v-for="(step, index) in WIZARD_STEPS"
            :key="step"
            class="flex-1 h-2 rounded-full transition-colors duration-300"
            :class="[
              index < currentStepIndex
                ? 'bg-green-500'
                : index === currentStepIndex
                  ? 'bg-blue-500'
                  : 'bg-gray-200',
            ]"
          />
        </div>
      </div>

      <!-- Loading State -->
      <div v-if="isLoading" class="flex-1 flex items-center justify-center py-12">
        <div class="flex flex-col items-center gap-3">
          <Loader2 class="h-8 w-8 animate-spin text-blue-500" />
          <p class="text-sm text-gray-500">{{ loadingMessage }}</p>
        </div>
      </div>

      <!-- Error State -->
      <div v-else-if="error" class="flex-1 p-6">
        <div class="p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3">
          <AlertCircle class="w-5 h-5 text-red-500 flex-shrink-0 mt-0.5" />
          <div>
            <h4 class="text-sm font-medium text-red-800">Error</h4>
            <p class="text-sm text-red-600">{{ error }}</p>
            <Button variant="outline" size="sm" @click="retryLoad" class="mt-2"> Retry </Button>
          </div>
        </div>
      </div>

      <!-- Content Area -->
      <div v-else class="flex-1 overflow-y-auto p-1">
        <!-- Description Step -->
        <div v-if="currentStep === 'description'" class="space-y-4">
          <SideBySideEditor
            title="Job Description"
            :original-content="content?.description || ''"
            :improved-content="improvedContent?.description"
            :is-generating="isGeneratingImprovement"
            @generate="generateDescriptionImprovement"
            @accept="acceptImprovement('description')"
            @reject="rejectImprovement('description')"
            @update:content="updateField('description', $event)"
          />
        </div>

        <!-- Tasks Step -->
        <div v-if="currentStep === 'tasks'" class="space-y-4">
          <div v-for="(task, index) in content?.tasks || []" :key="index" class="space-y-2">
            <h4 class="text-sm font-medium text-gray-700">
              Task {{ task.step_number }}: {{ task.summary || 'Untitled' }}
            </h4>
            <SideBySideEditor
              :title="`Task ${task.step_number} Description`"
              :original-content="task.description"
              :improved-content="improvedTasks[index]?.description"
              :is-generating="generatingTaskIndex === index"
              @generate="generateTaskImprovement(index)"
              @accept="acceptTaskImprovement(index, 'description')"
              @reject="rejectTaskImprovement(index)"
              @update:content="updateTaskField(index, 'description', $event)"
            />
          </div>
        </div>

        <!-- Hazards Step -->
        <div v-if="currentStep === 'hazards'" class="space-y-6">
          <div v-for="(task, index) in content?.tasks || []" :key="index" class="space-y-3">
            <div class="flex items-center justify-between">
              <h4 class="text-sm font-medium text-gray-700">
                Task {{ task.step_number }}: {{ task.summary || task.description?.slice(0, 50) }}
              </h4>
              <Button
                variant="outline"
                size="sm"
                @click="generateHazards(index)"
                :disabled="generatingHazardsIndex === index"
                class="gap-1"
              >
                <Loader2 v-if="generatingHazardsIndex === index" class="w-4 h-4 animate-spin" />
                <Sparkles v-else class="w-4 h-4" />
                Generate Hazards
              </Button>
            </div>
            <HazardsList
              :hazards="task.potential_hazards"
              :suggested-hazards="suggestedHazards[index] || []"
              @add="addHazard(index, $event)"
              @remove="removeHazard(index, $event)"
              @accept-suggestion="acceptSuggestedHazard(index, $event)"
            />
          </div>
        </div>

        <!-- Controls Step -->
        <div v-if="currentStep === 'controls'" class="space-y-6">
          <div v-for="(task, index) in content?.tasks || []" :key="index" class="space-y-3">
            <div class="flex items-center justify-between">
              <h4 class="text-sm font-medium text-gray-700">
                Task {{ task.step_number }}: {{ task.summary || task.description?.slice(0, 50) }}
              </h4>
              <Button
                variant="outline"
                size="sm"
                @click="generateControls(index)"
                :disabled="generatingControlsIndex === index || task.potential_hazards.length === 0"
                class="gap-1"
              >
                <Loader2 v-if="generatingControlsIndex === index" class="w-4 h-4 animate-spin" />
                <Sparkles v-else class="w-4 h-4" />
                Generate Controls
              </Button>
            </div>
            <ControlsList
              :controls="task.control_measures"
              :hazards="task.potential_hazards"
              :suggested-controls="suggestedControls[index] || []"
              @add="addControl(index, $event)"
              @remove="removeControl(index, $event)"
              @accept-suggestion="acceptSuggestedControl(index, $event)"
            />
          </div>
        </div>

        <!-- PPE Step -->
        <div v-if="currentStep === 'ppe'" class="space-y-4">
          <div class="flex items-center justify-between">
            <h4 class="text-sm font-medium text-gray-700">PPE Requirements</h4>
            <Button
              variant="outline"
              size="sm"
              @click="generatePPEImprovement"
              :disabled="isGeneratingPPE"
              class="gap-1"
            >
              <Loader2 v-if="isGeneratingPPE" class="w-4 h-4 animate-spin" />
              <Sparkles v-else class="w-4 h-4" />
              Improve with AI
            </Button>
          </div>
          <PPEEditor
            :ppe-requirements="content?.ppe_requirements || []"
            :suggested-ppe="suggestedPPE"
            @add="addPPE"
            @remove="removePPE"
            @accept-suggestion="acceptSuggestedPPE"
          />
        </div>

        <!-- Review Step -->
        <div v-if="currentStep === 'review'" class="space-y-4">
          <div class="bg-gray-50 rounded-lg p-4 border border-gray-200">
            <h4 class="text-sm font-medium text-gray-700 mb-3">Document Summary</h4>
            <dl class="space-y-2 text-sm">
              <div class="flex justify-between">
                <dt class="text-gray-500">Title</dt>
                <dd class="text-gray-900 font-medium">{{ content?.title }}</dd>
              </div>
              <div class="flex justify-between">
                <dt class="text-gray-500">Tasks</dt>
                <dd class="text-gray-900">{{ content?.tasks?.length || 0 }} tasks</dd>
              </div>
              <div class="flex justify-between">
                <dt class="text-gray-500">PPE Items</dt>
                <dd class="text-gray-900">{{ content?.ppe_requirements?.length || 0 }} items</dd>
              </div>
            </dl>
          </div>
          <div class="p-4 bg-blue-50 border border-blue-200 rounded-lg">
            <p class="text-sm text-blue-800">
              Click "Save to Google Doc" to save your changes. The document will be updated in
              Google Docs.
            </p>
          </div>
        </div>
      </div>

      <!-- Footer -->
      <DialogFooter class="flex-shrink-0 border-t pt-4 gap-2">
        <Button variant="ghost" @click="handleClose" :disabled="isSaving"> Cancel </Button>
        <div class="flex-1" />
        <Button
          v-if="currentStepIndex > 0"
          variant="outline"
          @click="previousStep"
          :disabled="isSaving"
        >
          <ChevronLeft class="w-4 h-4 mr-1" />
          Back
        </Button>
        <Button
          v-if="currentStepIndex < WIZARD_STEPS.length - 1"
          @click="nextStep"
          :disabled="isSaving"
        >
          Next
          <ChevronRight class="w-4 h-4 ml-1" />
        </Button>
        <Button
          v-else
          @click="saveDocument"
          :disabled="isSaving"
          class="bg-green-600 hover:bg-green-700"
        >
          <Loader2 v-if="isSaving" class="w-4 h-4 mr-2 animate-spin" />
          <Save v-else class="w-4 h-4 mr-2" />
          Save to Google Doc
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { toast } from 'vue-sonner'
import { Sparkles, Loader2, AlertCircle, ChevronLeft, ChevronRight, Save } from 'lucide-vue-next'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import SideBySideEditor from './SideBySideEditor.vue'
import HazardsList from './HazardsList.vue'
import ControlsList from './ControlsList.vue'
import PPEEditor from './PPEEditor.vue'
import { processDocumentsService } from '@/services/processDocuments.service'
import { useJsaSwpStore } from '@/stores/jsaSwpDocuments'
import type {
  SafetyDocumentContent,
  SafetyTask,
  ControlMeasure,
  WizardStep,
  SafetyDocumentType,
} from '@/types/processDocument.types'

interface Props {
  isOpen: boolean
  documentId: string
  documentType: SafetyDocumentType
  category: string
}

const props = defineProps<Props>()

const emit = defineEmits<{
  close: []
  saved: []
}>()

// Constants
const WIZARD_STEPS: WizardStep[] = ['description', 'tasks', 'hazards', 'controls', 'ppe', 'review']

const stepLabels: Record<WizardStep, string> = {
  loading: 'Loading',
  description: 'Review Description',
  tasks: 'Review Tasks',
  hazards: 'Review Hazards',
  controls: 'Review Controls',
  ppe: 'Review PPE',
  review: 'Final Review',
}

// Store
const store = useJsaSwpStore()

// State
const currentStep = ref<WizardStep>('description')
const content = ref<SafetyDocumentContent | null>(null)
const originalContent = ref<SafetyDocumentContent | null>(null)
const improvedContent = ref<Partial<SafetyDocumentContent> | null>(null)
const improvedTasks = ref<Record<number, Partial<SafetyTask>>>({})
const suggestedHazards = ref<Record<number, string[]>>({})
const suggestedControls = ref<Record<number, ControlMeasure[]>>({})
const suggestedPPE = ref<string[]>([])

// Loading states
const isLoading = ref(false)
const loadingMessage = ref('Loading document...')
const error = ref<string | null>(null)
const isSaving = ref(false)
const isGeneratingImprovement = ref(false)
const isGeneratingPPE = ref(false)
const generatingTaskIndex = ref<number | null>(null)
const generatingHazardsIndex = ref<number | null>(null)
const generatingControlsIndex = ref<number | null>(null)

// Computed
const currentStepIndex = computed(() => WIZARD_STEPS.indexOf(currentStep.value))

// Load document on open
watch(
  () => props.isOpen,
  async (isOpen) => {
    if (isOpen && props.documentId) {
      await loadDocument()
    }
  },
  { immediate: true },
)

async function loadDocument() {
  isLoading.value = true
  loadingMessage.value = 'Loading document from Google Docs...'
  error.value = null

  try {
    const docContent = await processDocumentsService.getProcedureContent(
      props.category,
      props.documentId,
    )
    content.value = docContent
    originalContent.value = JSON.parse(JSON.stringify(docContent))
    currentStep.value = 'description'
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Failed to load document'
  } finally {
    isLoading.value = false
  }
}

function retryLoad() {
  loadDocument()
}

function handleClose() {
  emit('close')
}

// Navigation
function nextStep() {
  const nextIndex = currentStepIndex.value + 1
  if (nextIndex < WIZARD_STEPS.length) {
    currentStep.value = WIZARD_STEPS[nextIndex]
  }
}

function previousStep() {
  const prevIndex = currentStepIndex.value - 1
  if (prevIndex >= 0) {
    currentStep.value = WIZARD_STEPS[prevIndex]
  }
}

// Description improvements
async function generateDescriptionImprovement() {
  if (!content.value?.description) return

  isGeneratingImprovement.value = true
  try {
    const improved = await processDocumentsService.improveSection(
      content.value.description,
      'description',
      `${props.documentType === 'jsa' ? 'Job Safety Analysis' : 'Safe Work Procedure'}`,
    )
    improvedContent.value = { ...improvedContent.value, description: improved }
  } catch {
    toast.error('Failed to generate improvement')
  } finally {
    isGeneratingImprovement.value = false
  }
}

function acceptImprovement(field: keyof SafetyDocumentContent) {
  if (improvedContent.value?.[field] && content.value) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(content.value as any)[field] = improvedContent.value[field]
    delete improvedContent.value[field]
  }
}

function rejectImprovement(field: keyof SafetyDocumentContent) {
  if (improvedContent.value) {
    delete improvedContent.value[field]
  }
}

function updateField(field: keyof SafetyDocumentContent, value: string) {
  if (content.value) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(content.value as any)[field] = value
  }
}

// Task improvements
async function generateTaskImprovement(taskIndex: number) {
  if (!content.value?.tasks?.[taskIndex]) return

  generatingTaskIndex.value = taskIndex
  try {
    const task = content.value.tasks[taskIndex]
    const improved = await processDocumentsService.improveSection(
      task.description,
      'task',
      content.value.description,
    )
    improvedTasks.value = {
      ...improvedTasks.value,
      [taskIndex]: { description: improved },
    }
  } catch {
    toast.error('Failed to generate task improvement')
  } finally {
    generatingTaskIndex.value = null
  }
}

function acceptTaskImprovement(taskIndex: number, field: keyof SafetyTask) {
  if (improvedTasks.value[taskIndex]?.[field] && content.value?.tasks?.[taskIndex]) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(content.value.tasks[taskIndex] as any)[field] = improvedTasks.value[taskIndex][field]
    delete improvedTasks.value[taskIndex]
  }
}

function rejectTaskImprovement(taskIndex: number) {
  delete improvedTasks.value[taskIndex]
}

function updateTaskField(taskIndex: number, field: keyof SafetyTask, value: string) {
  if (content.value?.tasks?.[taskIndex]) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    ;(content.value.tasks[taskIndex] as any)[field] = value
  }
}

// Hazards
async function generateHazards(taskIndex: number) {
  if (!content.value?.tasks?.[taskIndex]) return

  generatingHazardsIndex.value = taskIndex
  try {
    const task = content.value.tasks[taskIndex]
    const hazards = await processDocumentsService.generateHazards(task.description)
    // Filter out hazards that already exist
    const existingHazards = new Set(task.potential_hazards.map((h) => h.toLowerCase()))
    const newHazards = hazards.filter((h) => !existingHazards.has(h.toLowerCase()))
    suggestedHazards.value = { ...suggestedHazards.value, [taskIndex]: newHazards }
  } catch {
    toast.error('Failed to generate hazards')
  } finally {
    generatingHazardsIndex.value = null
  }
}

function addHazard(taskIndex: number, hazard: string) {
  if (content.value?.tasks?.[taskIndex]) {
    content.value.tasks[taskIndex].potential_hazards = [
      ...content.value.tasks[taskIndex].potential_hazards,
      hazard,
    ]
  }
}

function removeHazard(taskIndex: number, hazardIndex: number) {
  if (content.value?.tasks?.[taskIndex]) {
    content.value.tasks[taskIndex].potential_hazards = content.value.tasks[
      taskIndex
    ].potential_hazards.filter((_, i) => i !== hazardIndex)
  }
}

function acceptSuggestedHazard(taskIndex: number, hazard: string) {
  addHazard(taskIndex, hazard)
  // Remove from suggestions
  suggestedHazards.value = {
    ...suggestedHazards.value,
    [taskIndex]: suggestedHazards.value[taskIndex]?.filter((h) => h !== hazard) || [],
  }
}

// Controls
async function generateControls(taskIndex: number) {
  if (!content.value?.tasks?.[taskIndex]) return

  generatingControlsIndex.value = taskIndex
  try {
    const task = content.value.tasks[taskIndex]
    const controls = await processDocumentsService.generateControls(
      task.potential_hazards,
      task.description,
    )
    // Filter out controls that already exist
    const existingControls = new Set(task.control_measures.map((c: string) => c.toLowerCase()))
    const newControls = controls.filter((c: string) => !existingControls.has(c.toLowerCase()))
    suggestedControls.value = { ...suggestedControls.value, [taskIndex]: newControls }
  } catch {
    toast.error('Failed to generate controls')
  } finally {
    generatingControlsIndex.value = null
  }
}

function addControl(taskIndex: number, control: string) {
  if (content.value?.tasks?.[taskIndex]) {
    content.value.tasks[taskIndex].control_measures = [
      ...content.value.tasks[taskIndex].control_measures,
      control,
    ]
  }
}

function removeControl(taskIndex: number, controlIndex: number) {
  if (content.value?.tasks?.[taskIndex]) {
    content.value.tasks[taskIndex].control_measures = content.value.tasks[
      taskIndex
    ].control_measures.filter((_: string, i: number) => i !== controlIndex)
  }
}

function acceptSuggestedControl(taskIndex: number, control: string) {
  addControl(taskIndex, control)
  // Remove from suggestions
  suggestedControls.value = {
    ...suggestedControls.value,
    [taskIndex]: suggestedControls.value[taskIndex]?.filter((c: string) => c !== control) || [],
  }
}

// PPE
async function generatePPEImprovement() {
  if (!content.value) return

  isGeneratingPPE.value = true
  try {
    const currentPPE = content.value.ppe_requirements.join(', ')
    const improved = await processDocumentsService.improveSection(
      currentPPE,
      'ppe',
      content.value.description,
    )
    // Parse improved text into array (assuming comma-separated)
    const newItems = improved
      .split(/[,\n]/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0)
    const existingPPE = new Set(content.value.ppe_requirements.map((p) => p.toLowerCase()))
    suggestedPPE.value = newItems.filter((p) => !existingPPE.has(p.toLowerCase()))
  } catch {
    toast.error('Failed to generate PPE suggestions')
  } finally {
    isGeneratingPPE.value = false
  }
}

function addPPE(item: string) {
  if (content.value) {
    content.value.ppe_requirements = [...content.value.ppe_requirements, item]
  }
}

function removePPE(index: number) {
  if (content.value) {
    content.value.ppe_requirements = content.value.ppe_requirements.filter((_, i) => i !== index)
  }
}

function acceptSuggestedPPE(item: string) {
  addPPE(item)
  suggestedPPE.value = suggestedPPE.value.filter((p) => p !== item)
}

// Save
async function saveDocument() {
  if (!content.value) return

  isSaving.value = true
  try {
    await store.saveDocumentContent(props.category, props.documentId, content.value)
    emit('saved')
  } catch {
    toast.error('Failed to save document')
  } finally {
    isSaving.value = false
  }
}
</script>
