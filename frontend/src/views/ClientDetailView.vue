<template>
  <AppLayout>
    <div class="p-4 md:p-8 space-y-6">
      <!-- Header with Back Button -->
      <div class="flex items-center gap-4">
        <Button variant="outline" size="sm" @click="goBack">
          <ArrowLeft class="w-4 h-4 mr-2" />
          Back
        </Button>
        <div class="flex-1">
          <div v-if="isLoading" class="flex items-center gap-2">
            <Loader2 class="w-5 h-5 animate-spin text-indigo-600" />
            <span class="text-gray-500">Loading client...</span>
          </div>
          <div v-else-if="client" class="flex items-center gap-3">
            <Users class="w-6 h-6 text-indigo-600" />
            <div>
              <h1 class="text-2xl font-bold text-gray-900">{{ client.name }}</h1>
              <div class="flex items-center gap-2 mt-1">
                <Badge :variant="client.is_account_customer ? 'default' : 'secondary'">
                  {{ client.is_account_customer ? 'Account Customer' : 'Cash Customer' }}
                </Badge>
                <Badge v-if="client.is_supplier" variant="outline"> Supplier </Badge>
                <Badge
                  v-if="client.xero_contact_id"
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
        <p class="text-lg font-medium text-gray-900">Failed to load client</p>
        <p class="text-sm text-gray-500 mt-2">{{ error }}</p>
        <Button @click="loadClientData" class="mt-4"> Try Again </Button>
      </div>

      <!-- Tabs -->
      <Tabs v-else-if="client" v-model="activeTab" class="w-full">
        <TabsList class="grid w-full grid-cols-3">
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
                <p class="text-gray-900">{{ client.name }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Email</label>
                <p class="text-gray-900">{{ client.email || '-' }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Phone</label>
                <p class="text-gray-900">{{ client.phone || '-' }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Address</label>
                <p class="text-gray-900">{{ client.address || '-' }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Primary Contact</label>
                <p class="text-gray-900">{{ client.primary_contact_name || '-' }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Primary Contact Email</label>
                <p class="text-gray-900">{{ client.primary_contact_email || '-' }}</p>
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
                v-if="clientStore.isLoadingContacts"
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
                      <p class="font-medium text-gray-900">{{ contact.name }}</p>
                      <Badge v-if="contact.is_primary" variant="default" class="text-xs"
                        >Primary</Badge
                      >
                    </div>
                    <p v-if="contact.position" class="text-sm text-gray-500">
                      {{ contact.position }}
                    </p>
                    <div class="flex flex-col gap-1 mt-1 text-sm text-gray-600">
                      <span v-if="contact.email">{{ contact.email }}</span>
                      <span v-if="contact.phone">{{ contact.phone }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
          </Card>

          <!-- Xero Integration Details -->
          <Card v-if="client.xero_contact_id">
            <CardHeader>
              <CardTitle>Xero Integration</CardTitle>
            </CardHeader>
            <CardContent class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label class="text-sm font-medium text-gray-500">Xero Contact ID</label>
                <p class="text-gray-900 font-mono text-xs">{{ client.xero_contact_id }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Last Modified</label>
                <p class="text-gray-900">{{ formatDateTime(client.xero_last_modified) }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Last Synced</label>
                <p class="text-gray-900">{{ formatDateTime(client.xero_last_synced) }}</p>
              </div>
              <div>
                <label class="text-sm font-medium text-gray-500">Status</label>
                <Badge :variant="client.xero_archived ? 'destructive' : 'default'">
                  {{ client.xero_archived ? 'Archived' : 'Active' }}
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
                <p class="text-3xl font-bold text-indigo-600 mt-2">
                  {{ client.total_spend || '$0.00' }}
                </p>
              </div>
              <div class="p-4 bg-green-50 rounded-lg">
                <label class="text-sm font-medium text-green-900">Last Invoice Date</label>
                <p class="text-2xl font-bold text-green-600 mt-2">
                  {{ client.last_invoice_date || 'No invoices' }}
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
                <Badge :variant="client.is_account_customer ? 'default' : 'secondary'">
                  {{ client.is_account_customer ? 'Account Customer' : 'Cash Customer' }}
                </Badge>
              </div>
              <div class="flex justify-between items-center py-2 border-b">
                <span class="text-gray-600">Also a Supplier</span>
                <Badge :variant="client.is_supplier ? 'default' : 'outline'">
                  {{ client.is_supplier ? 'Yes' : 'No' }}
                </Badge>
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
              <div v-if="clientStore.isLoadingJobs" class="flex items-center justify-center py-8">
                <Loader2 class="w-6 h-6 animate-spin text-indigo-600" />
              </div>
              <div v-else-if="relatedJobs.length === 0" class="text-center py-12 text-gray-500">
                <Briefcase class="w-12 h-12 mx-auto mb-4 text-gray-400" />
                <p class="text-lg font-medium">No jobs found</p>
                <p class="text-sm">This client doesn't have any jobs yet</p>
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
      </Tabs>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useClientStore } from '@/stores/clientStore'
import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  ArrowLeft,
  Users,
  FileText,
  DollarSign,
  Briefcase,
  Loader2,
  AlertCircle,
  CheckCircle2,
  UserCircle,
} from 'lucide-vue-next'
import { toast } from 'vue-sonner'

interface Props {
  id: string
}

const props = defineProps<Props>()
const router = useRouter()
const clientStore = useClientStore()

// State
const activeTab = ref('details')
const isLoading = ref(false)
const error = ref<string | null>(null)

// Computed
const client = computed(() => {
  return clientStore.detailedClients[props.id]
})

const contacts = computed(() => {
  return clientStore.clientContacts[props.id] || []
})

const relatedJobs = computed(() => {
  return clientStore.clientJobs[props.id] || []
})

/**
 * Display job as "quoted" if either:
 * - has_quote_in_xero: A Xero quote object exists, OR
 * - is_fixed_price: Job was quoted in person (no Xero quote created)
 */
const isJobQuoted = (job: (typeof relatedJobs.value)[0]): boolean => {
  return job.has_quote_in_xero || job.is_fixed_price
}

// Methods
async function loadClientData() {
  isLoading.value = true
  error.value = null

  try {
    // Load client details
    await clientStore.fetchClientDetail(props.id)

    // Load contacts
    try {
      await clientStore.fetchClientContacts(props.id)
    } catch (err) {
      console.error('Failed to load contacts:', err)
      // Don't show error for contacts, just log it
    }

    // Load related jobs
    try {
      await clientStore.fetchClientJobs(props.id)
    } catch (err) {
      console.error('Failed to load jobs:', err)
      // Don't show error for jobs, just log it
    }
  } catch (err) {
    const errorMessage =
      err instanceof Error ? err.message : 'An error occurred while loading client data'
    error.value = errorMessage
    toast.error('Failed to load client details')
    console.error('Error loading client:', err)
  } finally {
    isLoading.value = false
  }
}

function goBack() {
  router.push({ name: 'clients' })
}

function navigateToJob(jobId: string) {
  router.push({ name: 'job-edit', params: { id: jobId } })
}

function formatDateTime(dateString: string | null | undefined): string {
  if (!dateString) return '-'
  try {
    const date = new Date(dateString)
    return date.toLocaleString('en-AU', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return dateString
  }
}

// Lifecycle
onMounted(() => {
  loadClientData()
})
</script>
