<template>
  <AppLayout>
    <main class="mx-auto w-full max-w-6xl space-y-6 p-4 md:p-8">
      <header class="flex items-center gap-4">
        <Button type="button" variant="outline" size="sm" @click="router.push('/crm/people')">
          <ArrowLeft class="mr-2 h-4 w-4" /> People
        </Button>
        <div>
          <h1 class="text-3xl font-bold text-gray-900">{{ person?.name || 'Person' }}</h1>
          <p class="text-sm text-gray-600">
            Manage identity, contact methods, and company relationships.
          </p>
        </div>
      </header>

      <div v-if="loading" class="flex min-h-64 items-center justify-center text-gray-500">
        <Loader2 class="mr-2 h-6 w-6 animate-spin" /> Loading person…
      </div>
      <div v-else-if="error" class="rounded-lg border border-red-200 bg-red-50 p-6 text-red-800">
        {{ error }}
      </div>

      <template v-else-if="person">
        <Card>
          <CardHeader><CardTitle>Identity</CardTitle></CardHeader>
          <CardContent class="grid gap-4 md:grid-cols-2">
            <div>
              <label class="mb-1 block text-sm font-medium text-gray-700">Name</label>
              <Input v-model="identityName" data-automation-id="PersonDetail-name" />
            </div>
            <div>
              <label class="mb-1 block text-sm font-medium text-gray-700">Email</label>
              <Input v-model="identityEmail" type="email" data-automation-id="PersonDetail-email" />
            </div>
            <div class="md:col-span-2">
              <Button
                type="button"
                :disabled="savingIdentity || !identityName.trim()"
                data-automation-id="PersonDetail-save-identity"
                @click="saveIdentity"
              >
                Save identity
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>Contact methods</CardTitle></CardHeader>
          <CardContent class="space-y-4">
            <div class="grid gap-3 md:grid-cols-[10rem_1fr_1fr_auto_auto]">
              <select
                v-model="methodType"
                class="rounded-md border border-gray-300 px-3 py-2 text-sm"
              >
                <option value="phone">Phone</option>
                <option value="email">Email</option>
              </select>
              <Input
                v-model="methodValue"
                placeholder="Phone or email"
                data-automation-id="PersonDetail-method-value"
              />
              <Input v-model="methodLabel" placeholder="Label" />
              <label class="flex items-center gap-2 rounded-md border px-3 py-2 text-sm">
                <input v-model="methodPrimary" type="checkbox" /> Primary
              </label>
              <div class="flex gap-2">
                <Button
                  type="button"
                  :disabled="savingMethod || !methodValue.trim()"
                  data-automation-id="PersonDetail-save-method"
                  @click="saveMethod"
                >
                  {{ editingMethodId ? 'Update' : 'Add' }}
                </Button>
                <Button
                  v-if="editingMethodId"
                  type="button"
                  variant="outline"
                  @click="resetMethodForm"
                  >Cancel</Button
                >
              </div>
            </div>
            <div class="overflow-x-auto rounded-md border">
              <table class="w-full text-sm">
                <thead class="border-b bg-slate-50 text-left">
                  <tr>
                    <th class="p-3">Type</th>
                    <th class="p-3">Value</th>
                    <th class="p-3">Label</th>
                    <th class="p-3">Primary</th>
                    <th class="p-3 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-if="contactMethods.length === 0">
                    <td colspan="5" class="p-6 text-center text-gray-500">No contact methods</td>
                  </tr>
                  <tr
                    v-for="method in contactMethods"
                    :key="method.id"
                    class="border-b last:border-b-0"
                  >
                    <td class="p-3 capitalize">{{ method.method_type }}</td>
                    <td class="p-3">{{ method.value }}</td>
                    <td class="p-3">{{ method.label || '—' }}</td>
                    <td class="p-3">{{ method.is_primary ? 'Yes' : '—' }}</td>
                    <td class="p-3">
                      <div class="flex justify-end gap-2">
                        <Button type="button" variant="ghost" size="sm" @click="editMethod(method)"
                          >Edit</Button
                        ><Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          class="text-red-700"
                          @click="removeMethod(method.id)"
                          >Remove</Button
                        >
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Company links</CardTitle>
            <p class="text-sm text-gray-600">
              Active and inactive relationships are retained here.
            </p>
          </CardHeader>
          <CardContent class="space-y-4">
            <div class="grid gap-3 lg:grid-cols-[1fr_1fr_1fr_auto_auto]">
              <CompanyLookup
                id="person-link-company"
                v-model="linkCompanyName"
                label="Company"
                :required="true"
                :search-mode="true"
                @update:selected-company="linkCompany = $event"
              />
              <div>
                <label class="mb-1 block text-sm font-medium text-gray-700">Position</label
                ><Input v-model="linkPosition" />
              </div>
              <div>
                <label class="mb-1 block text-sm font-medium text-gray-700">Notes</label
                ><Input v-model="linkNotes" />
              </div>
              <label class="mt-6 flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
                ><input v-model="linkPrimary" type="checkbox" /> Primary</label
              >
              <Button
                type="button"
                class="mt-6"
                :disabled="!editingCompanyId && !linkCompany"
                data-automation-id="PersonDetail-save-link"
                @click="saveLink"
                >{{ editingCompanyId ? 'Update' : 'Add link' }}</Button
              >
              <Button
                v-if="editingCompanyId"
                type="button"
                class="mt-6"
                variant="outline"
                @click="resetLinkForm"
              >
                Cancel
              </Button>
            </div>
            <div class="space-y-3">
              <div
                v-for="link in companyLinks"
                :key="link.company_id"
                class="flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center sm:justify-between"
                :class="
                  link.is_active ? 'border-gray-200' : 'border-gray-300 bg-gray-50 opacity-75'
                "
                :data-automation-id="`PersonDetail-company-link-${link.company_id}`"
              >
                <div>
                  <div class="flex items-center gap-2">
                    <p class="font-medium text-gray-900">{{ link.company_name }}</p>
                    <Badge :variant="link.is_active ? 'default' : 'secondary'">{{
                      link.is_active ? 'Active' : 'Inactive'
                    }}</Badge
                    ><Badge v-if="link.is_primary" variant="outline">Primary</Badge>
                  </div>
                  <p class="text-sm text-gray-600">
                    {{ link.position || 'No position'
                    }}<span v-if="link.notes"> · {{ link.notes }}</span>
                  </p>
                </div>
                <div class="flex gap-2">
                  <Button type="button" variant="outline" size="sm" @click="editLink(link)"
                    >Edit</Button
                  ><Button
                    v-if="link.is_active"
                    type="button"
                    variant="outline"
                    size="sm"
                    class="text-red-700"
                    :data-automation-id="`PersonDetail-remove-link-${link.company_id}`"
                    @click="removeLink(link.company_id)"
                    >Remove</Button
                  ><Button
                    v-else
                    type="button"
                    size="sm"
                    :data-automation-id="`PersonDetail-restore-link-${link.company_id}`"
                    @click="restoreLink(link)"
                    >Restore</Button
                  ><Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    @click="openCompany(link.company_id)"
                    >Company</Button
                  >
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </template>
    </main>
  </AppLayout>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import type { z } from 'zod'
import { ArrowLeft, Loader2 } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

import { api } from '@/api/client'
import { schemas } from '@/api/generated/api'
import AppLayout from '@/components/AppLayout.vue'
import CompanyLookup from '@/components/CompanyLookup.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { extractErrorMessage } from '@/utils/error-handler'

const props = defineProps<{ id: string }>()
type PersonDetail = z.infer<typeof schemas.PersonDetail>
type ContactMethod = z.infer<typeof schemas.ContactMethod>
type PersonCompanyLink = z.infer<typeof schemas.PersonCompanyLink>
type Company = z.infer<typeof schemas.CompanySearchResult>
type MethodType = z.infer<typeof schemas.ContactMethodTypeEnum>

const router = useRouter()
const person = ref<PersonDetail | null>(null)
const contactMethods = ref<ContactMethod[]>([])
const companyLinks = ref<PersonCompanyLink[]>([])
const loading = ref(false)
const error = ref<string | null>(null)
const savingIdentity = ref(false)
const identityName = ref('')
const identityEmail = ref('')
const savingMethod = ref(false)
const editingMethodId = ref('')
const methodType = ref<MethodType>('phone')
const methodValue = ref('')
const methodLabel = ref('')
const methodPrimary = ref(false)
const editingCompanyId = ref('')
const linkCompany = ref<Company | null>(null)
const linkCompanyName = ref('')
const linkPosition = ref('')
const linkNotes = ref('')
const linkPrimary = ref(false)

async function loadPerson(): Promise<void> {
  loading.value = true
  error.value = null
  try {
    const [detail, methods, links] = await Promise.all([
      api.people_retrieve({ params: { person_id: props.id } }),
      api.people_contact_methods_list({ params: { person_id: props.id } }),
      api.people_company_links_list({ params: { person_id: props.id } }),
    ])
    person.value = detail
    contactMethods.value = methods
    companyLinks.value = links
    identityName.value = detail.name
    identityEmail.value = detail.email || ''
  } catch (err) {
    error.value = err instanceof Error ? err.message : 'Failed to load person'
    toast.error('Failed to load person')
  } finally {
    loading.value = false
  }
}

async function saveIdentity(): Promise<void> {
  savingIdentity.value = true
  try {
    await api.people_partial_update(
      { name: identityName.value.trim(), email: identityEmail.value.trim() || null },
      { params: { person_id: props.id } },
    )
    toast.success('Identity updated')
    await loadPerson()
  } catch {
    toast.error('Failed to update identity')
  } finally {
    savingIdentity.value = false
  }
}

async function saveMethod(): Promise<void> {
  savingMethod.value = true
  const body = {
    method_type: methodType.value,
    value: methodValue.value.trim(),
    label: methodLabel.value.trim(),
    is_primary: methodPrimary.value,
  }
  try {
    if (editingMethodId.value)
      await api.people_contact_methods_partial_update(body, {
        params: { person_id: props.id, method_id: editingMethodId.value },
      })
    else await api.people_contact_methods_create(body, { params: { person_id: props.id } })
    toast.success('Contact method saved')
    resetMethodForm()
    contactMethods.value = await api.people_contact_methods_list({
      params: { person_id: props.id },
    })
  } catch (err) {
    toast.error(err instanceof Error ? err.message : 'Failed to save contact method')
  } finally {
    savingMethod.value = false
  }
}

function editMethod(method: ContactMethod): void {
  editingMethodId.value = method.id
  methodType.value = method.method_type
  methodValue.value = method.value
  methodLabel.value = method.label || ''
  methodPrimary.value = Boolean(method.is_primary)
}
function resetMethodForm(): void {
  editingMethodId.value = ''
  methodType.value = 'phone'
  methodValue.value = ''
  methodLabel.value = ''
  methodPrimary.value = false
}
async function removeMethod(methodId: string): Promise<void> {
  if (!window.confirm('Remove this contact method?')) return
  try {
    await api.people_contact_methods_destroy(undefined, {
      params: { person_id: props.id, method_id: methodId },
    })
    contactMethods.value = contactMethods.value.filter((method) => method.id !== methodId)
    toast.success('Contact method removed')
  } catch (err) {
    toast.error(`Contact method not removed: ${extractErrorMessage(err)}`)
  }
}

async function saveLink(): Promise<void> {
  const companyId = editingCompanyId.value || linkCompany.value?.id
  if (!companyId) return
  try {
    await api.people_company_links_update(
      {
        position: linkPosition.value.trim() || null,
        notes: linkNotes.value.trim() || null,
        is_primary: linkPrimary.value,
      },
      { params: { person_id: props.id, company_id: companyId } },
    )
    toast.success(editingCompanyId.value ? 'Company link updated' : 'Company linked')
    resetLinkForm()
    companyLinks.value = await api.people_company_links_list({ params: { person_id: props.id } })
  } catch (err) {
    toast.error(`Company link not saved: ${extractErrorMessage(err)}`)
  }
}
function editLink(link: PersonCompanyLink): void {
  editingCompanyId.value = link.company_id
  linkCompanyName.value = link.company_name
  linkPosition.value = link.position || ''
  linkNotes.value = link.notes || ''
  linkPrimary.value = link.is_primary
}
function resetLinkForm(): void {
  editingCompanyId.value = ''
  linkCompany.value = null
  linkCompanyName.value = ''
  linkPosition.value = ''
  linkNotes.value = ''
  linkPrimary.value = false
}
async function removeLink(companyId: string): Promise<void> {
  if (!window.confirm('Remove this company link?')) return
  try {
    await api.people_company_links_destroy(undefined, {
      params: { person_id: props.id, company_id: companyId },
    })
    companyLinks.value = await api.people_company_links_list({ params: { person_id: props.id } })
    toast.success('Company link removed')
  } catch (err) {
    toast.error(`Company link not removed: ${extractErrorMessage(err)}`)
  }
}
async function restoreLink(link: PersonCompanyLink): Promise<void> {
  try {
    await api.people_company_links_update(
      { position: link.position, notes: link.notes, is_primary: link.is_primary },
      { params: { person_id: props.id, company_id: link.company_id } },
    )
    companyLinks.value = await api.people_company_links_list({ params: { person_id: props.id } })
    toast.success('Company link restored')
  } catch (err) {
    toast.error(`Company link not restored: ${extractErrorMessage(err)}`)
  }
}
function openCompany(companyId: string): void {
  router.push({ name: '/crm/companies/[id]', params: { id: companyId } })
}

onMounted(loadPerson)
</script>
