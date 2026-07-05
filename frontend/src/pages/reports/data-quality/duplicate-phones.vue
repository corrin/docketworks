<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="flex-1 overflow-y-auto p-0">
        <div class="max-w-7xl mx-auto py-8 px-2 md:px-8 h-full flex flex-col gap-6">
          <!-- Header -->
          <div class="flex items-center justify-between mb-4">
            <h1 class="text-3xl font-extrabold text-indigo-700 flex items-center gap-3">
              <PhoneCall class="w-8 h-8 text-amber-500" />
              Duplicate Phones
            </h1>
            <div class="flex items-center gap-2">
              <Button
                variant="outline"
                @click="exportReport"
                :disabled="loading || !duplicates.length"
                class="text-sm px-4 py-2"
              >
                <Download class="w-4 h-4 mr-2" />
                Export CSV
              </Button>
              <Button
                variant="outline"
                @click="refreshData"
                :disabled="loading"
                class="text-sm px-4 py-2"
              >
                <RefreshCw class="w-4 h-4 mr-2" :class="{ 'animate-spin': loading }" />
                Refresh
              </Button>
            </div>
          </div>

          <!-- Summary Stats -->
          <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center gap-3">
                <Users class="w-5 h-5 text-amber-500" />
                <div>
                  <p class="text-sm text-slate-600">Cross-client</p>
                  <p class="text-2xl font-bold text-amber-600">{{ summary.cross_client }}</p>
                </div>
              </div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center gap-3">
                <Building2 class="w-5 h-5 text-blue-500" />
                <div>
                  <p class="text-sm text-slate-600">Internal line</p>
                  <p class="text-2xl font-bold text-blue-600">{{ summary.internal_line }}</p>
                </div>
              </div>
            </div>
            <div class="bg-white rounded-lg shadow-sm border border-slate-200 p-4">
              <div class="flex items-center gap-3">
                <Clock class="w-5 h-5 text-slate-500" />
                <div>
                  <p class="text-sm text-slate-600">Last Run</p>
                  <p class="text-sm font-semibold">{{ lastRunTime }}</p>
                </div>
              </div>
            </div>
          </div>

          <!-- Loading State -->
          <div
            v-if="loading"
            class="flex-1 flex items-center justify-center text-2xl text-slate-400"
          >
            <RefreshCw class="w-8 h-8 animate-spin mr-2" />
            Loading duplicate phones report...
          </div>

          <!-- Error State -->
          <div
            v-else-if="error"
            class="flex-1 flex items-center justify-center text-xl text-red-500"
          >
            <AlertCircle class="w-8 h-8 mr-2" />
            {{ error }}
          </div>

          <!-- No Issues State -->
          <div
            v-else-if="!loading && duplicates.length === 0"
            class="flex-1 flex items-center justify-center"
          >
            <div class="text-center">
              <CheckCircle class="w-16 h-16 text-green-500 mx-auto mb-4" />
              <h2 class="text-2xl font-semibold text-slate-800 mb-2">All Clear!</h2>
              <p class="text-slate-600">No duplicate or mis-owned phone numbers found.</p>
            </div>
          </div>

          <!-- Duplicates Table -->
          <div
            v-else-if="!loading && duplicates.length > 0"
            class="flex-1 bg-white rounded-lg shadow-sm border border-slate-200 overflow-hidden flex flex-col"
          >
            <div class="p-4 border-b border-slate-200">
              <h2 class="text-lg font-semibold text-slate-800">
                Duplicate Phones ({{ duplicates.length }})
              </h2>
            </div>
            <div class="overflow-auto flex-1">
              <table class="w-full">
                <thead class="bg-slate-50 border-b border-slate-200">
                  <tr>
                    <th class="text-left px-4 py-3 text-sm font-semibold text-slate-700">
                      Phone Number
                    </th>
                    <th class="text-left px-4 py-3 text-sm font-semibold text-slate-700">Issue</th>
                    <th class="text-left px-4 py-3 text-sm font-semibold text-slate-700">
                      Endpoint
                    </th>
                    <th class="text-left px-4 py-3 text-sm font-semibold text-slate-700">Owners</th>
                  </tr>
                </thead>
                <tbody class="divide-y divide-slate-200">
                  <tr
                    v-for="duplicate in duplicates"
                    :key="duplicate.normalized_value"
                    class="hover:bg-slate-50 align-top"
                  >
                    <td class="px-4 py-3 text-sm font-medium text-slate-900">
                      {{ duplicate.normalized_value }}
                    </td>
                    <td class="px-4 py-3">
                      <span
                        :class="getIssueClass(duplicate.issue)"
                        class="px-2 py-1 text-xs font-medium rounded-full"
                      >
                        {{ issueLabel(duplicate.issue) }}
                      </span>
                    </td>
                    <td class="px-4 py-3 text-sm text-slate-600">
                      {{ duplicate.endpoint_label ?? '—' }}
                    </td>
                    <td class="px-4 py-3 text-sm text-slate-700">
                      <div class="flex flex-col gap-1">
                        <span
                          v-for="owner in duplicate.owners"
                          :key="owner.method_id"
                          class="flex items-center gap-2"
                        >
                          <span class="font-medium">{{ owner.owner_name }}</span>
                          <span
                            class="px-2 py-0.5 text-xs rounded-full bg-slate-100 text-slate-600"
                          >
                            {{ ownerKindLabel(owner.owner_kind) }}
                          </span>
                        </span>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import AppLayout from '@/components/AppLayout.vue'
import Button from '@/components/ui/button/Button.vue'
import {
  PhoneCall,
  RefreshCw,
  Download,
  Users,
  Building2,
  CheckCircle,
  AlertCircle,
  Clock,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { exportToCsv, formatDateTime } from '@/utils/string-formatting'
import { toLocalDateString } from '@/utils/dateUtils'
import type { z } from 'zod'

type DuplicatePhone = z.infer<typeof schemas.DuplicatePhoneIssue>
type DuplicatePhoneSummary = z.infer<typeof schemas.DuplicatePhoneSummary>

const loading = ref(false)
const error = ref<string | null>(null)
const duplicates = ref<DuplicatePhone[]>([])
const summary = ref<DuplicatePhoneSummary>({ cross_client: 0, internal_line: 0 })
const lastRunTime = ref<string>('Never')

// Known issue/owner kinds get styled labels; unknown future kinds render the
// raw value with neutral styling instead of being mislabeled.
const ISSUE_LABELS: Record<string, string> = {
  cross_client: 'Cross-client',
  internal_line: 'Internal line',
}

const ISSUE_CLASSES: Record<string, string> = {
  cross_client: 'bg-amber-100 text-amber-800',
  internal_line: 'bg-blue-100 text-blue-800',
}

const OWNER_KIND_LABELS: Record<string, string> = {
  client: 'Client',
  contact: 'Contact',
}

const issueLabel = (issue: string): string => ISSUE_LABELS[issue] ?? issue

const getIssueClass = (issue: string): string =>
  ISSUE_CLASSES[issue] ?? 'bg-slate-100 text-slate-800'

const ownerKindLabel = (kind: string): string => OWNER_KIND_LABELS[kind] ?? kind

const refreshData = async () => {
  loading.value = true
  error.value = null

  try {
    const data = await api.check_duplicate_phones()

    duplicates.value = data.duplicate_phones
    summary.value = data.summary
    lastRunTime.value = formatDateTime(data.checked_at)

    if (duplicates.value.length === 0) {
      toast.success('No duplicate phone numbers found!')
    } else {
      toast.warning(`Found ${duplicates.value.length} duplicate phone numbers`)
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load duplicate phones report'
    toast.error('Failed to load duplicate phones report')
  } finally {
    loading.value = false
  }
}

const exportReport = () => {
  if (!duplicates.value.length) return

  const headers = ['Phone Number', 'Issue', 'Endpoint', 'Owners']
  const rows = duplicates.value.map((duplicate) => [
    duplicate.normalized_value,
    issueLabel(duplicate.issue),
    duplicate.endpoint_label ?? '',
    duplicate.owners
      .map((owner) => `${owner.owner_name} (${ownerKindLabel(owner.owner_kind)})`)
      .join('; '),
  ])

  exportToCsv(headers, rows, `duplicate-phones-${toLocalDateString()}`)
  toast.success('Report exported successfully')
}

onMounted(() => {
  refreshData()
})
</script>
