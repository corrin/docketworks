<template>
  <AppLayout>
    <div class="h-full w-full overflow-y-auto">
      <main class="mx-auto flex max-w-7xl flex-col gap-6 px-3 py-8 md:px-8">
        <header class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <h1 class="flex items-center gap-3 text-3xl font-extrabold text-indigo-700">
              <Fingerprint class="h-8 w-8 text-amber-500" />
              Duplicate Identities
            </h1>
            <p class="mt-2 text-sm text-slate-600">
              Compact company and person groups, with automatic matches separated from genuine
              exceptions.
            </p>
          </div>
          <Button
            variant="outline"
            class="self-start text-sm"
            :disabled="loading"
            data-automation-id="duplicate-identities-refresh"
            @click="refreshData"
          >
            <RefreshCw class="mr-2 h-4 w-4" :class="{ 'animate-spin': loading }" />
            Refresh
          </Button>
        </header>

        <section class="grid grid-cols-2 gap-3 lg:grid-cols-5" aria-label="Report summary">
          <SummaryCard label="Company review" :value="summary.company_review_groups" tone="amber" />
          <SummaryCard label="Person review" :value="summary.person_review_groups" tone="amber" />
          <SummaryCard
            label="Company auto"
            :value="summary.company_merge_groups"
            :tone="summary.company_merge_groups === 0 ? 'green' : 'red'"
          />
          <SummaryCard
            label="Person auto"
            :value="summary.person_merge_groups"
            :tone="summary.person_merge_groups === 0 ? 'green' : 'red'"
          />
          <div
            class="col-span-2 rounded-lg border border-slate-200 bg-white p-4 shadow-sm lg:col-span-1"
          >
            <p class="text-sm text-slate-600">Last run</p>
            <p class="mt-1 text-sm font-semibold text-slate-900">{{ lastRunTime }}</p>
          </div>
        </section>

        <div
          v-if="loading"
          class="flex min-h-64 items-center justify-center text-xl text-slate-400"
          data-automation-id="duplicate-identities-loading"
        >
          <RefreshCw class="mr-2 h-7 w-7 animate-spin" />
          Loading duplicate identities…
        </div>

        <div
          v-else-if="error"
          class="flex min-h-64 items-center justify-center text-xl text-red-600"
          data-automation-id="duplicate-identities-error"
        >
          <AlertCircle class="mr-2 h-7 w-7" />
          {{ error }}
        </div>

        <template v-else>
          <div
            v-if="automaticGroups.length > 0"
            class="rounded-lg border border-red-300 bg-red-50 p-4 text-red-900"
            data-automation-id="duplicate-identities-auto-warning"
          >
            <div class="flex items-start gap-3">
              <ShieldAlert class="mt-0.5 h-5 w-5 shrink-0" />
              <div>
                <p class="font-semibold">
                  {{ automaticGroups.length }} automatic
                  {{ automaticGroups.length === 1 ? 'group remains' : 'groups remain' }}
                </p>
                <p class="mt-1 text-sm">
                  These groups meet the automatic merge rules and should normally be cleared by the
                  cleanup process. They are shown below for diagnosis, not manual assessment.
                </p>
              </div>
            </div>
          </div>

          <div
            v-else
            class="rounded-lg border border-green-300 bg-green-50 p-4 text-green-900"
            data-automation-id="duplicate-identities-auto-clear"
          >
            <div class="flex items-center gap-3">
              <CheckCircle2 class="h-5 w-5 shrink-0" />
              <div>
                <p class="font-semibold">Automatic duplicates are clear</p>
                <p class="text-sm">Only genuine exceptions needing a decision appear below.</p>
              </div>
            </div>
          </div>

          <section v-if="reviewGroups.length > 0" class="space-y-3">
            <div class="flex items-end justify-between gap-4">
              <div>
                <h2 class="text-xl font-bold text-slate-900">Needs review</h2>
                <p class="text-sm text-slate-600">
                  Shared details conflict or may represent a person legitimately linked to multiple
                  companies.
                </p>
              </div>
              <span
                class="rounded-full bg-amber-100 px-3 py-1 text-sm font-semibold text-amber-900"
              >
                {{ reviewGroups.length }} groups
              </span>
            </div>
            <IdentityGroupCard
              v-for="group in reviewGroups"
              :key="`${group.entityKind}-${group.group.group_id}`"
              :entity-kind="group.entityKind"
              :group="group.group"
            />
          </section>

          <section v-if="automaticGroups.length > 0" class="space-y-3">
            <div>
              <h2 class="text-xl font-bold text-slate-900">Automatic matches</h2>
              <p class="text-sm text-slate-600">Strong matches awaiting automatic cleanup.</p>
            </div>
            <IdentityGroupCard
              v-for="group in automaticGroups"
              :key="`${group.entityKind}-${group.group.group_id}`"
              :entity-kind="group.entityKind"
              :group="group.group"
            />
          </section>

          <div
            v-if="reviewGroups.length === 0 && automaticGroups.length === 0"
            class="flex min-h-64 items-center justify-center"
            data-automation-id="duplicate-identities-all-clear"
          >
            <div class="text-center">
              <CheckCircle2 class="mx-auto mb-4 h-16 w-16 text-green-500" />
              <h2 class="mb-2 text-2xl font-semibold text-slate-800">All clear</h2>
              <p class="text-slate-600">No duplicate company or person groups remain.</p>
            </div>
          </div>
        </template>
      </main>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import type { z } from 'zod'
import { AlertCircle, CheckCircle2, Fingerprint, RefreshCw, ShieldAlert } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import AppLayout from '@/components/AppLayout.vue'
import IdentityGroupCard from '@/components/data-quality/IdentityGroupCard.vue'
import SummaryCard from '@/components/data-quality/SummaryCard.vue'
import Button from '@/components/ui/button/Button.vue'
import { formatDateTime } from '@/utils/string-formatting'

type CompanyGroup = z.infer<typeof schemas.DuplicateCompanyGroup>
type PersonGroup = z.infer<typeof schemas.DuplicatePersonGroup>
type Summary = z.infer<typeof schemas.DuplicateIdentityReportSummary>

type GroupItem =
  | { entityKind: 'company'; group: CompanyGroup }
  | { entityKind: 'person'; group: PersonGroup }

const EMPTY_SUMMARY: Summary = {
  company_merge_groups: 0,
  company_review_groups: 0,
  person_merge_groups: 0,
  person_review_groups: 0,
}

const loading = ref(false)
const error = ref<string | null>(null)
const companyGroups = ref<CompanyGroup[]>([])
const personGroups = ref<PersonGroup[]>([])
const summary = ref<Summary>(EMPTY_SUMMARY)
const lastRunTime = ref('Never')

const allGroups = computed<GroupItem[]>(() => [
  ...companyGroups.value.map((group) => ({ entityKind: 'company' as const, group })),
  ...personGroups.value.map((group) => ({ entityKind: 'person' as const, group })),
])

const reviewGroups = computed(() =>
  allGroups.value.filter(({ group }) => group.recommendation === 'review'),
)

const automaticGroups = computed(() =>
  allGroups.value.filter(({ group }) => group.recommendation === 'merge'),
)

async function refreshData(): Promise<void> {
  loading.value = true
  error.value = null

  try {
    const data = await api.check_duplicate_identities()
    companyGroups.value = data.company_groups
    personGroups.value = data.person_groups
    summary.value = data.summary
    lastRunTime.value = formatDateTime(data.checked_at)

    if (automaticGroups.value.length > 0) {
      toast.warning(`Found ${automaticGroups.value.length} automatic duplicate groups`)
    } else if (reviewGroups.value.length > 0) {
      toast.info(`${reviewGroups.value.length} duplicate identity groups need review`)
    } else {
      toast.success('No duplicate identities found')
    }
  } catch (err) {
    companyGroups.value = []
    personGroups.value = []
    summary.value = EMPTY_SUMMARY
    error.value = err instanceof Error ? err.message : 'Failed to load duplicate identities report'
    toast.error('Failed to load duplicate identities report')
  } finally {
    loading.value = false
  }
}

onMounted(refreshData)
</script>
