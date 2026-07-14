<template>
  <AppLayout>
    <main class="mx-auto w-full max-w-7xl space-y-6 p-4 md:p-8">
      <header class="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 class="flex items-center gap-3 text-3xl font-bold text-gray-900">
            <Users class="h-8 w-8 text-indigo-600" /> People
          </h1>
          <p class="mt-1 text-sm text-gray-600">
            One identity per person, linked to every company they work with.
          </p>
        </div>
        <Button
          type="button"
          data-automation-id="PeopleDirectory-create"
          @click="showCreate = !showCreate"
        >
          <UserPlus class="mr-2 h-4 w-4" /> Create or link person
        </Button>
      </header>

      <Card v-if="showCreate" data-automation-id="PeopleDirectory-create-panel">
        <CardHeader>
          <CardTitle>Create or link a person</CardTitle>
          <p class="text-sm text-gray-600">
            Choose the company first. Every new person requires a company link.
          </p>
        </CardHeader>
        <CardContent class="grid gap-4 lg:grid-cols-2">
          <CompanyLookup
            id="people-company"
            v-model="selectedCompanyName"
            label="Company"
            :required="true"
            :search-mode="true"
            @update:selected-company="selectedCompany = $event"
          />
          <PersonSelector
            id="directory-person"
            label="Person"
            :optional="true"
            :company-id="selectedCompany?.id ?? ''"
            :company-name="selectedCompany?.name ?? ''"
            placeholder="Choose a company first"
            @update:selected-person="personAdded"
          />
        </CardContent>
      </Card>

      <Card>
        <CardContent class="pt-6">
          <div class="flex flex-col gap-3 sm:flex-row">
            <Input
              v-model="searchInput"
              placeholder="Search name, email, phone, or company"
              data-automation-id="PeopleDirectory-search"
              @keydown.enter.prevent="applySearch"
            />
            <Button type="button" variant="outline" @click="applySearch">
              <Search class="mr-2 h-4 w-4" /> Search
            </Button>
          </div>
        </CardContent>
      </Card>

      <div v-if="loading" class="flex min-h-64 items-center justify-center text-gray-500">
        <Loader2 class="mr-2 h-6 w-6 animate-spin" /> Loading people…
      </div>
      <div v-else-if="error" class="rounded-lg border border-red-200 bg-red-50 p-6 text-red-800">
        {{ error }}
      </div>
      <Card v-else>
        <CardContent class="p-0">
          <div class="overflow-x-auto">
            <table class="w-full text-sm">
              <thead class="border-b bg-slate-50 text-left text-gray-600">
                <tr>
                  <th class="p-4 font-semibold">Person</th>
                  <th class="p-4 font-semibold">Phone</th>
                  <th class="p-4 font-semibold">Companies</th>
                  <th class="p-4 text-right font-semibold">Action</th>
                </tr>
              </thead>
              <tbody>
                <tr v-if="people.length === 0">
                  <td colspan="4" class="p-8 text-center text-gray-500">No people found</td>
                </tr>
                <tr
                  v-for="person in people"
                  :key="person.id"
                  class="border-b last:border-b-0 hover:bg-slate-50"
                  :data-automation-id="`PeopleDirectory-row-${person.id}`"
                >
                  <td class="p-4">
                    <p class="font-medium text-gray-900">{{ person.name }}</p>
                    <p class="text-gray-500">{{ person.email || 'No email' }}</p>
                  </td>
                  <td class="p-4 text-gray-700">{{ person.primary_phone || '—' }}</td>
                  <td class="p-4 text-gray-700">
                    {{ person.companies.map((company) => company.company_name).join(', ') || '—' }}
                  </td>
                  <td class="p-4 text-right">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      :data-automation-id="`PeopleDirectory-open-${person.id}`"
                      @click="openPerson(person.id)"
                    >
                      Manage
                    </Button>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="flex items-center justify-between border-t p-4">
            <p class="text-sm text-gray-600">{{ count }} people</p>
            <div class="flex items-center gap-2">
              <Button
                type="button"
                variant="outline"
                size="sm"
                :disabled="page <= 1"
                @click="goToPage(page - 1)"
              >
                Previous
              </Button>
              <span class="text-sm text-gray-600">Page {{ page }} of {{ totalPages || 1 }}</span>
              <Button
                type="button"
                variant="outline"
                size="sm"
                :disabled="page >= totalPages"
                @click="goToPage(page + 1)"
              >
                Next
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
    </main>
  </AppLayout>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { z } from 'zod'
import { Loader2, Search, UserPlus, Users } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import AppLayout from '@/components/AppLayout.vue'
import CompanyLookup from '@/components/CompanyLookup.vue'
import PersonSelector from '@/components/PersonSelector.vue'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

type PersonSummary = z.infer<typeof schemas.PersonSummary>
type Company = z.infer<typeof schemas.CompanySearchResult>
type CompanyPerson = z.infer<typeof schemas.CompanyPerson>

const router = useRouter()
const people = ref<PersonSummary[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const page = ref(1)
const totalPages = ref(0)
const count = ref(0)
const query = ref('')
const searchInput = ref('')
const showCreate = ref(false)
const selectedCompany = ref<Company | null>(null)
const selectedCompanyName = ref('')

async function loadPeople(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const response = await api.people_list({
      queries: { page: page.value, page_size: 50, q: query.value || undefined },
    })
    people.value = response.results
    count.value = response.count
    totalPages.value = response.total_pages
    page.value = response.page
  } catch (err) {
    people.value = []
    error.value = err instanceof Error ? err.message : 'Failed to load people'
    toast.error('Failed to load people')
  } finally {
    loading.value = false
  }
}

function applySearch(): void {
  query.value = searchInput.value.trim()
  page.value = 1
  void loadPeople()
}

function goToPage(nextPage: number): void {
  page.value = nextPage
  void loadPeople()
}

function openPerson(personId: string): void {
  router.push({ name: '/crm/people/[id]', params: { id: personId } })
}

function personAdded(person: CompanyPerson | null): void {
  if (!person) return
  showCreate.value = false
  selectedCompany.value = null
  selectedCompanyName.value = ''
  void loadPeople()
}

onMounted(loadPeople)
</script>
