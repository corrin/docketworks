<template>
  <AppLayout>
    <div class="p-4 md:p-8 space-y-6">
      <!-- Header with Back Button -->
      <div class="flex items-center gap-4">
        <Button variant="outline" size="sm" data-automation-id="CompanyDetail-back" @click="goBack">
          <ArrowLeft class="w-4 h-4 mr-2" />
          Back
        </Button>
        <div class="flex-1">
          <div v-if="isLoading" class="flex items-center gap-2">
            <Loader2 class="w-5 h-5 animate-spin text-indigo-600" />
            <span class="text-gray-500">Loading company...</span>
          </div>
          <div v-else-if="company" class="flex items-center gap-3">
            <Users class="w-6 h-6 text-indigo-600" />
            <div>
              <h1 class="text-2xl font-bold text-gray-900">{{ company.name }}</h1>
              <div class="flex items-center gap-2 mt-1">
                <Badge :variant="company.is_account_customer ? 'default' : 'secondary'">
                  {{ company.is_account_customer ? 'Account Customer' : 'Cash Customer' }}
                </Badge>
                <Badge v-if="company.is_supplier" variant="outline"> Supplier </Badge>
                <Badge v-if="!company.allow_jobs" variant="destructive"> Jobs Blocked </Badge>
                <Badge
                  v-if="company.xero_contact_id"
                  variant="outline"
                  class="flex items-center gap-1"
                >
                  <CheckCircle2 class="w-3 h-3" />
                  Xero Synced
                </Badge>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Error State -->
      <div v-if="error && !isLoading" class="text-center py-12">
        <AlertCircle class="w-12 h-12 mx-auto mb-4 text-red-500" />
        <p class="text-lg font-medium text-gray-900">Failed to load company</p>
        <p class="text-sm text-gray-500 mt-2">{{ error }}</p>
        <Button @click="loadCompanyData" class="mt-4"> Try Again </Button>
      </div>

      <!-- Tabs -->
      <Tabs v-else-if="company" v-model="activeTab" class="w-full">
        <TabsList class="grid w-full grid-cols-4">
          <TabsTrigger value="details">
            <FileText class="w-4 h-4 mr-2" />
            Details & Contacts
          </TabsTrigger>
          <TabsTrigger value="financial">
            <DollarSign class="w-4 h-4 mr-2" />
            Financial Summary
          </TabsTrigger>
          <TabsTrigger value="jobs">
            <Briefcase class="w-4 h-4 mr-2" />
            Related Jobs
          </TabsTrigger>
          <TabsTrigger value="interactions">
            <Phone class="w-4 h-4 mr-2" />
            Interactions
          </TabsTrigger>
        </TabsList>

        <!-- Details & Contacts Tab -->
        <TabsContent value="details" class="space-y-6 mt-6">
          <!-- Basic Information -->
          <Card>
            <CardHeader>
              <CardTitle>Basic Information</CardTitle>
            </CardHeader>
            <CardContent class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="text-sm font-medium text-gray-500">Name</label>
                <p class="text-gray-900">{{ company.name }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Email</label>
                <p class="text-gray-900">{{ company.email || '-' }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Address</label>
                <p class="text-gray-900">{{ company.address || '-' }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Primary Person</label>
                <p class="text-gray-900">{{ primaryPerson?.person_name || '-' }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Primary Person Email</label>
                <p class="text-gray-900">{{ primaryPerson?.person_email || '-' }}</p>
              </div>
            </CardContent>
          </Card>

          <!-- Supplier Search Aliases -->
          <Card>
            <CardHeader>
              <CardTitle>Supplier Search Aliases</CardTitle>
            </CardHeader>
            <CardContent class="space-y-4">
              <div class="flex gap-2">
                <Input
                  v-model="newAlias"
                  placeholder="Add supplier search alias"
                  data-automation-id="CompanyDetailView-alias-input"
                  @keydown.enter.prevent="createSupplierAlias"
                />
                <Button
                  type="button"
                  :disabled="isSavingAlias || !newAlias.trim()"
                  data-automation-id="CompanyDetailView-alias-add"
                  @click="createSupplierAlias"
                >
                  <Plus class="w-4 h-4 mr-2" />
                  Add
                </Button>
              </div>

              <div
                v-if="isLoadingAliases"
                class="flex items-center justify-center py-4"
                data-automation-id="CompanyDetailView-alias-loading"
              >
                <Loader2 class="w-5 h-5 animate-spin text-indigo-600" />
              </div>
              <div
                v-else-if="supplierAliases.length === 0"
                class="text-sm text-gray-500"
                data-automation-id="CompanyDetailView-alias-empty"
              >
                No supplier search aliases
              </div>
              <div v-else class="flex flex-wrap gap-2">
                <div
                  v-for="alias in supplierAliases"
                  :key="alias.id"
                  class="inline-flex items-center gap-2 rounded-md border border-gray-200 bg-gray-50 px-2 py-1 text-sm"
                  :data-automation-id="`CompanyDetailView-alias-${alias.id}`"
                >
                  <span>{{ alias.alias }}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    class="h-6 w-6 p-0"
                    :aria-label="`Remove alias ${alias.alias}`"
                    :data-automation-id="`CompanyDetailView-alias-remove-${alias.id}`"
                    @click="deleteSupplierAlias(alias.id)"
                  >
                    <X class="w-3 h-3" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>

          <!-- Contact Persons -->
          <Card>
            <CardHeader>
              <CardTitle>Contact Persons</CardTitle>
            </CardHeader>
            <CardContent>
              <div
                v-if="companyStore.isLoadingContacts"
                class="flex items-center justify-center py-8"
              >
                <Loader2 class="w-6 h-6 animate-spin text-indigo-600" />
              </div>
              <div v-else-if="contacts.length === 0" class="text-center py-8 text-gray-500">
                <UserCircle class="w-12 h-12 mx-auto mb-2 text-gray-400" />
                <p>No additional contacts</p>
              </div>
              <div v-else class="space-y-3">
                <div
                  v-for="contact in contacts"
                  :key="contact.id"
                  class="flex items-start gap-3 p-3 border border-gray-200 rounded-lg"
                >
                  <UserCircle class="w-5 h-5 text-gray-400 mt-0.5" />
                  <div class="flex-1">
                    <div class="flex items-center gap-2">
                      <p class="font-medium text-gray-900">{{ contact.person_name }}</p>
                      <Badge v-if="contact.is_primary" variant="default" class="text-xs"
                        >Primary</Badge
                      >
                    </div>
                    <p v-if="contact.position" class="text-sm text-gray-500">
                      {{ contact.position }}
                    </p>
                    <div class="flex flex-col gap-1 mt-1 text-sm text-gray-600">
                      <span v-if="contact.person_email">{{ contact.person_email }}</span>
                      <span v-if="contact.phone">{{ contact.phone }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          <PhoneNumberManager
            title="Phone Numbers"
            :fixed-company-id="props.id"
            :fixed-company-name="company.name"
            search-context="crm_client_detail_phone_numbers"
            @changed="loadPhoneCalls"
          />

          <!-- Xero Integration Details -->
          <Card v-if="company.xero_contact_id">
            <CardHeader>
              <CardTitle>Xero Integration</CardTitle>
            </CardHeader>
            <CardContent class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="text-sm font-medium text-gray-500">Xero Contact ID</label>
                <p class="text-gray-900 font-mono text-xs">{{ company.xero_contact_id }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Last Modified</label>
                <p class="text-gray-900">{{ formatDateTime(company.xero_last_modified) }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Last Synced</label>
                <p class="text-gray-900">{{ formatDateTime(company.xero_last_synced) }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Status</label>
                <Badge :variant="company.xero_archived ? 'destructive' : 'default'">
                  {{ company.xero_archived ? 'Archived' : 'Active' }}
                </Badge>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <!-- Financial Summary Tab -->
        <TabsContent value="financial" class="space-y-6 mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Financial Summary</CardTitle>
            </CardHeader>
            <CardContent class="grid grid-cols-1 md:grid-cols-2 gap-6">
              <div class="p-4 bg-indigo-50 rounded-lg">
                <label class="text-sm font-medium text-indigo-900">Total Spend</label>
                <p
                  class="text-3xl font-bold text-indigo-600 mt-2"
                  data-automation-id="CompanyDetail-total-spend"
                >
                  {{ company.total_spend || '$0.00' }}
                </p>
              </div>
              <div class="p-4 bg-green-50 rounded-lg">
                <label class="text-sm font-medium text-green-900">Last Invoice Date</label>
                <p class="text-2xl font-bold text-green-600 mt-2">
                  {{ company.last_invoice_date || 'No invoices' }}
                </p>
              </div>
            </CardContent>
          </Card>

          <!-- Additional Financial Info -->
          <Card>
            <CardHeader>
              <CardTitle>Account Information</CardTitle>
            </CardHeader>
            <CardContent class="space-y-3">
              <div class="flex justify-between items-center py-2 border-b">
                <span class="text-gray-600">Account Type</span>
                <Badge :variant="company.is_account_customer ? 'default' : 'secondary'">
                  {{ company.is_account_customer ? 'Account Customer' : 'Cash Customer' }}
                </Badge>
              </div>
              <div class="flex justify-between items-center py-2 border-b">
                <span class="text-gray-600">Also a Supplier</span>
                <Badge :variant="company.is_supplier ? 'default' : 'outline'">
                  {{ company.is_supplier ? 'Yes' : 'No' }}
                </Badge>
              </div>
              <div class="py-2 border-b">
                <div class="flex justify-between items-center">
                  <div>
                    <span class="text-gray-600">Allow Jobs</span>
                    <p class="text-xs text-gray-500 mt-0.5">
                      When disabled, this company cannot be selected when creating jobs.
                    </p>
                  </div>
                  <Switch
                    :checked="company.allow_jobs"
                    :disabled="isSavingAllowJobs"
                    aria-label="Allow jobs for this company"
                    @update:checked="onAllowJobsToggle"
                  />
                </div>
                <p v-if="allowJobsBlockedReason" class="mt-2 text-xs text-amber-700">
                  {{ allowJobsBlockedReason }}
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <!-- Related Jobs Tab -->
        <TabsContent value="jobs" class="space-y-6 mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Related Jobs</CardTitle>
            </CardHeader>
            <CardContent>
              <div v-if="companyStore.isLoadingJobs" class="flex items-center justify-center py-8">
                <Loader2 class="w-6 h-6 animate-spin text-indigo-600" />
              </div>
              <div v-else-if="relatedJobs.length === 0" class="text-center py-12 text-gray-500">
                <Briefcase class="w-12 h-12 mx-auto mb-4 text-gray-400" />
                <p class="text-lg font-medium">No jobs found</p>
                <p class="text-sm">This company doesn't have any jobs yet</p>
              </div>
              <div v-else class="overflow-x-auto">
                <table class="min-w-full text-sm">
                  <thead class="bg-slate-50 border-b">
                    <tr>
                      <th class="p-3 text-left font-semibold text-gray-700">Job #</th>
                      <th class="p-3 text-left font-semibold text-gray-700">Job Name</th>
                      <th class="p-3 text-left font-semibold text-gray-700">Status</th>
                      <th class="p-3 text-left font-semibold text-gray-700">Quoted</th>
                      <th class="p-3 text-left font-semibold text-gray-700">Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="job in relatedJobs"
                      :key="job.job_id"
                      class="border-b hover:bg-slate-50"
                    >
                      <td class="p-3 text-gray-600">#{{ job.job_number }}</td>
                      <td class="p-3 font-medium text-gray-900">{{ job.name }}</td>
                      <td class="p-3">
                        <Badge>{{ job.status }}</Badge>
                      </td>
                      <td class="p-3">
                        <Badge :variant="isJobQuoted(job) ? 'default' : 'secondary'">
                          {{ isJobQuoted(job) ? 'Yes' : 'No' }}
                        </Badge>
                      </td>
                      <td class="p-3">
                        <Button variant="outline" size="sm" @click="navigateToJob(job.job_id)">
                          View
                        </Button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <!-- Interactions Tab -->
        <TabsContent value="interactions" class="space-y-6 mt-6">
          <Card>
            <CardHeader>
              <div class="flex items-center justify-between gap-3">
                <CardTitle>Interactions</CardTitle>
                <div class="flex items-center gap-2">
                  <Badge variant="outline"
                    >Showing {{ phoneCalls.length }} of {{ phoneCallCount }}</Badge
                  >
                  <Button variant="outline" size="sm" @click="loadPhoneCalls">Refresh</Button>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div v-if="isLoadingPhoneCalls" class="flex items-center justify-center py-8">
                <Loader2 class="w-6 h-6 animate-spin text-indigo-600" />
              </div>
              <div v-else-if="phoneCallError" class="text-sm text-red-600">
                {{ phoneCallError }}
              </div>
              <PhoneCallTable
                v-else
                :calls="phoneCalls"
                empty-text="No phone interactions found for this company"
                @call-updated="replacePhoneCall"
              />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  </AppLayout>
</template>

<route lang="json">
{
  "props": true
}
</route>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useCompanyStore } from '@/stores/companyStore'
import AppLayout from '@/components/AppLayout.vue'
import PhoneCallTable from '@/components/crm/PhoneCallTable.vue'
import PhoneNumberManager from '@/components/crm/PhoneNumberManager.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  ArrowLeft,
  Users,
  FileText,
  DollarSign,
  Briefcase,
  Phone,
  Loader2,
  AlertCircle,
  CheckCircle2,
  UserCircle,
  Plus,
  X,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import { formatDateTime } from '@/utils/string-formatting'
import type { z } from 'zod'

interface Props {
  id: string
}

const props = defineProps<Props>()
const router = useRouter()
const companyStore = useCompanyStore()
type SupplierSearchAlias = z.infer<typeof schemas.SupplierSearchAlias>
type PhoneCallRecord = z.infer<typeof schemas.PhoneCallRecord>

// State
const activeTab = ref('details')
const isLoading = ref(false)
const error = ref<string | null>(null)
const isSavingAllowJobs = ref(false)
const isLoadingAliases = ref(false)
const isSavingAlias = ref(false)
const newAlias = ref('')
const supplierAliases = ref<SupplierSearchAlias[]>([])
const phoneCalls = ref<PhoneCallRecord[]>([])
const phoneCallCount = ref(0)
const isLoadingPhoneCalls = ref(false)
const phoneCallError = ref<string | null>(null)

// Computed
const company = computed(() => {
  return companyStore.detailedCompanies[props.id]
})

const contacts = computed(() => {
  return companyStore.companyContacts[props.id] || []
})

const primaryPerson = computed(() => {
  return contacts.value.find((contact) => contact.is_primary) ?? contacts.value[0] ?? null
})

const relatedJobs = computed(() => {
  return companyStore.companyJobs[props.id] || []
})

/**
 * Display job as "quoted" if either:
 * - has_quote_in_xero: A Xero quote object exists, OR
 * - is_fixed_price: Job was quoted in person (no Xero quote created)
 */
const isJobQuoted = (job: (typeof relatedJobs.value)[0]): boolean => {
  return job.has_quote_in_xero || job.is_fixed_price
}

/**
 * Explain why allow_jobs is likely blocked by upstream Xero state.
 * Shown as informational text — the admin may still override the toggle manually.
 */
const allowJobsBlockedReason = computed<string | null>(() => {
  const current = company.value
  if (!current) return null
  if (current.merged_into) {
    return 'Blocked because this contact was merged into another company in Xero.'
  }
  if (current.xero_archived) {
    return 'Blocked because this contact is archived in Xero.'
  }
  return null
})

async function onAllowJobsToggle(nextValue: boolean) {
  const current = company.value
  if (!current) return

  isSavingAllowJobs.value = true
  try {
    const result = await api.companies_update_update(
      { allow_jobs: nextValue },
      { params: { company_id: props.id } },
    )
    if (!result.success || !result.company) {
      throw new Error(result.message || 'Failed to update company')
    }
    companyStore.detailedCompanies = {
      ...companyStore.detailedCompanies,
      [props.id]: result.company,
    }
    toast.success(nextValue ? 'Company can now be used for jobs' : 'Company blocked from new jobs')
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to update company'
    console.error('Error updating allow_jobs:', err)
    toast.error(message)
  } finally {
    isSavingAllowJobs.value = false
  }
}

async function loadSupplierAliases() {
  isLoadingAliases.value = true
  try {
    supplierAliases.value = await api.companies_supplier_aliases_list({
      params: { company_id: props.id },
    })
  } catch (err) {
    console.error('Failed to load supplier aliases:', err)
    supplierAliases.value = []
    toast.error('Failed to load supplier aliases')
  } finally {
    isLoadingAliases.value = false
  }
}

async function createSupplierAlias() {
  const alias = newAlias.value.trim()
  if (!alias || isSavingAlias.value) return

  isSavingAlias.value = true
  try {
    const created = await api.companies_supplier_aliases_create(
      { alias },
      { params: { company_id: props.id } },
    )
    supplierAliases.value = [
      ...supplierAliases.value.filter((existing) => existing.id !== created.id),
      created,
    ].sort((a, b) => a.alias.localeCompare(b.alias))
    newAlias.value = ''
    toast.success('Supplier alias added')
  } catch (err) {
    console.error('Failed to add supplier alias:', err)
    toast.error('Failed to add supplier alias')
  } finally {
    isSavingAlias.value = false
  }
}

async function deleteSupplierAlias(aliasId: string) {
  try {
    await api.companies_supplier_aliases_destroy(undefined, {
      params: { alias_id: aliasId },
    })
    supplierAliases.value = supplierAliases.value.filter((alias) => alias.id !== aliasId)
    toast.success('Supplier alias removed')
  } catch (err) {
    console.error('Failed to remove supplier alias:', err)
    toast.error('Failed to remove supplier alias')
  }
}

async function loadPhoneCalls() {
  isLoadingPhoneCalls.value = true
  phoneCallError.value = null
  try {
    const response = await api.crm_phone_calls_list({
      queries: { company: props.id, page: 1, page_size: 50 },
    })
    phoneCalls.value = response.results
    phoneCallCount.value = response.count
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to load phone interactions'
    phoneCallError.value = message
    console.error('Failed to load phone interactions:', err)
    toast.error(message)
    phoneCalls.value = []
    phoneCallCount.value = 0
  } finally {
    isLoadingPhoneCalls.value = false
  }
}

function replacePhoneCall(updated: PhoneCallRecord) {
  phoneCalls.value = phoneCalls.value.map((call) => (call.id === updated.id ? updated : call))
}

// Methods
async function loadCompanyData() {
  isLoading.value = true
  error.value = null

  try {
    // Load company details
    await companyStore.fetchCompanyDetail(props.id)

    // Load supplier aliases
    await loadSupplierAliases()

    // Load contacts
    try {
      await companyStore.fetchCompanyPersonLinks(props.id)
    } catch (err) {
      console.error('Failed to load contacts:', err)
      // Don't show error for contacts, just log it
    }

    // Load related jobs
    try {
      await companyStore.fetchCompanyJobs(props.id)
    } catch (err) {
      console.error('Failed to load jobs:', err)
      // Don't show error for jobs, just log it
    }

    // Load phone interactions
    await loadPhoneCalls()
  } catch (err) {
    const errorMessage =
      err instanceof Error ? err.message : 'An error occurred while loading company data'
    error.value = errorMessage
    toast.error('Failed to load company details')
    console.error('Error loading company:', err)
  } finally {
    isLoading.value = false
  }
}

function goBack() {
  router.push({ name: '/crm/companies/(index)' })
}

function navigateToJob(jobId: string) {
  router.push({ name: '/jobs/[id]/(index)', params: { id: jobId } })
}

// Lifecycle
onMounted(() => {
  loadCompanyData()
})
</script>
