<template>
  <AppLayout>
    <div class="max-w-4xl mx-auto py-8 px-4 bg-white min-h-screen">
      <!-- Header -->
      <div class="mb-8">
        <h1 class="text-3xl font-bold text-gray-900 mb-2">UAT Server Management</h1>
        <p class="text-gray-600">Manage the UAT (User Acceptance Testing) server instance on AWS</p>
      </div>

      <!-- Status Card -->
      <div class="bg-white rounded-lg shadow-md border border-gray-200 p-6 mb-6">
        <div class="flex items-center justify-between mb-4">
          <h2 class="text-xl font-semibold text-gray-900">Server Status</h2>
          <button
            @click="refreshStatus"
            :disabled="isLoading"
            class="text-sm text-blue-600 hover:text-blue-800 disabled:opacity-50 transition-colors"
          >
            <RefreshCw :class="{ 'animate-spin': isLoading }" class="w-4 h-4 inline mr-1" />
            Refresh
          </button>
        </div>

        <div v-if="instanceStatus" class="space-y-4">
          <!-- Status Badge -->
          <div class="flex items-center space-x-3">
            <div class="flex items-center space-x-2">
              <component
                :is="statusIconComponent"
                :class="[
                  'w-5 h-5',
                  isTransitioning ? 'animate-pulse' : '',
                  statusClass.split(' ')[0],
                ]"
              />
              <span :class="['px-3 py-1 rounded-full text-sm font-medium capitalize', statusClass]">
                {{ instanceStatus.state }}
              </span>
            </div>
            <div v-if="isPolling" class="flex items-center text-sm text-gray-500">
              <div class="w-2 h-2 bg-blue-500 rounded-full animate-ping mr-2"></div>
              Auto-refreshing...
            </div>
          </div>

          <!-- Instance Details -->
          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Instance ID</label>
              <p class="text-sm text-gray-900 font-mono">
                {{ instanceStatus.instance_id || 'N/A' }}
              </p>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Public IP</label>
              <p class="text-sm text-gray-900 font-mono">{{ instanceStatus.public_ip || 'N/A' }}</p>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Private IP</label>
              <p class="text-sm text-gray-900 font-mono">
                {{ instanceStatus.private_ip || 'N/A' }}
              </p>
            </div>
            <div>
              <label class="block text-sm font-medium text-gray-700 mb-1">Instance Type</label>
              <p class="text-sm text-gray-900">{{ instanceStatus.instance_type || 'N/A' }}</p>
            </div>
          </div>

          <!-- Progress Message -->
          <div v-if="isTransitioning" class="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <div class="flex items-center">
              <div class="w-4 h-4 bg-blue-500 rounded-full animate-pulse mr-3"></div>
              <p class="text-blue-800 text-sm">
                Instance is
                {{ instanceStatus.state === 'pending' ? 'starting up' : 'shutting down' }}. This
                process typically takes 2-3 minutes.
              </p>
            </div>
          </div>
        </div>

        <div v-else-if="isLoading" class="flex justify-center items-center h-32">
          <div class="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600"></div>
        </div>

        <div v-else class="text-center text-gray-500 py-8">
          <AlertCircle class="w-8 h-8 mx-auto mb-2" />
          <p>Unable to load instance status</p>
        </div>
      </div>

      <!-- Error Message -->
      <div v-if="error" class="bg-red-50 border border-red-200 rounded-lg p-4 mb-6">
        <div class="flex items-start">
          <AlertTriangle class="w-5 h-5 text-red-600 mr-2 mt-0.5" />
          <div>
            <p class="text-red-800 font-medium">Error</p>
            <p class="text-red-700 text-sm mt-1">{{ error }}</p>
          </div>
        </div>
      </div>

      <!-- Actions -->
      <div class="bg-gray-50 rounded-lg p-6">
        <h3 class="text-lg font-semibold text-gray-900 mb-4">Actions</h3>

        <div class="flex flex-wrap gap-3">
          <!-- Start Button -->
          <Button
            v-if="showStartButton"
            @click="startInstance"
            :disabled="!canStart || isLoading"
            variant="default"
            size="lg"
            class="flex items-center"
          >
            <Play class="w-4 h-4 mr-2" />
            Start UAT Server
          </Button>

          <!-- Stop Button -->
          <Button
            v-if="showStopButton"
            @click="handleStopClick"
            :disabled="!canStop || isLoading"
            variant="destructive"
            size="lg"
            class="flex items-center"
          >
            <Square class="w-4 h-4 mr-2" />
            Stop UAT Server
          </Button>

          <!-- Reboot Button -->
          <Button
            v-if="showRebootButton"
            @click="handleRebootClick"
            :disabled="!canReboot || isLoading"
            variant="outline"
            size="lg"
            class="flex items-center"
          >
            <RotateCcw class="w-4 h-4 mr-2" />
            Reboot Server
          </Button>

          <!-- Open UAT Site Button -->
          <Button
            v-if="isRunning"
            @click="openUATSite"
            variant="outline"
            size="lg"
            class="flex items-center"
          >
            <ExternalLink class="w-4 h-4 mr-2" />
            Open UAT Site
          </Button>
        </div>

        <!-- Status Info -->
        <div class="mt-6 pt-4 border-t border-gray-200">
          <div class="flex items-center text-sm text-gray-600">
            <Info class="w-4 h-4 mr-2" />
            <span>
              UAT Site URL:
              <a
                :href="uatUrl"
                target="_blank"
                class="text-blue-600 hover:text-blue-800 underline font-mono"
              >
                {{ uatUrl }}
              </a>
            </span>
          </div>
        </div>
      </div>
    </div>

    <!-- Confirmation Dialog -->
    <Dialog v-model:open="showConfirmDialog">
      <DialogContent class="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{{ confirmAction === 'stop' ? 'Stop' : 'Reboot' }} UAT Server</DialogTitle>
          <DialogDescription>
            Are you sure you want to {{ confirmAction }} the UAT server?
            {{
              confirmAction === 'stop'
                ? 'This will make the UAT site unavailable.'
                : 'This will restart the server and may cause brief downtime.'
            }}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter class="flex justify-end space-x-2">
          <Button variant="outline" @click="showConfirmDialog = false"> Cancel </Button>
          <Button
            :variant="confirmAction === 'stop' ? 'destructive' : 'default'"
            @click="confirmActionHandler"
            :disabled="isLoading"
          >
            {{ confirmAction === 'stop' ? 'Stop Server' : 'Reboot Server' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import AppLayout from '@/components/AppLayout.vue'
import Button from '@/components/ui/button/Button.vue'
import Dialog from '@/components/ui/dialog/Dialog.vue'
import DialogContent from '@/components/ui/dialog/DialogContent.vue'
import DialogHeader from '@/components/ui/dialog/DialogHeader.vue'
import DialogTitle from '@/components/ui/dialog/DialogTitle.vue'
import DialogDescription from '@/components/ui/dialog/DialogDescription.vue'
import DialogFooter from '@/components/ui/dialog/DialogFooter.vue'
import {
  RefreshCw,
  Play,
  Square,
  RotateCcw,
  ExternalLink,
  Info,
  AlertTriangle,
  AlertCircle,
  CheckCircle,
  XCircle,
  Clock,
  HelpCircle,
} from 'lucide-vue-next'
import { useUATManagement } from '@/composables/useUATManagement'

const {
  instanceStatus,
  isLoading,
  error,
  isPolling,
  uatUrl,
  canStart,
  canStop,
  canReboot,
  isRunning,
  isTransitioning,
  showStartButton,
  showStopButton,
  showRebootButton,
  statusClass,
  statusIcon,
  refreshStatus,
  startInstance,
  stopInstance,
  rebootInstance,
  openUATSite,
} = useUATManagement()

// Confirmation dialog state
const showConfirmDialog = ref(false)
const confirmAction = ref<'stop' | 'reboot'>('stop')

// Status icon component mapping
const statusIconComponent = computed(() => {
  switch (statusIcon.value) {
    case 'CheckCircle':
      return CheckCircle
    case 'XCircle':
      return XCircle
    case 'Clock':
      return Clock
    case 'AlertTriangle':
      return AlertTriangle
    case 'HelpCircle':
    default:
      return HelpCircle
  }
})

// Confirmation handlers
const handleStopClick = () => {
  confirmAction.value = 'stop'
  showConfirmDialog.value = true
}

const handleRebootClick = () => {
  confirmAction.value = 'reboot'
  showConfirmDialog.value = true
}

const confirmActionHandler = async () => {
  showConfirmDialog.value = false

  if (confirmAction.value === 'stop') {
    await stopInstance()
  } else {
    await rebootInstance()
  }
}
</script>

<style scoped>
/* Additional styles if needed */
</style>
