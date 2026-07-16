<template>
  <details
    class="group rounded-lg border bg-white shadow-sm"
    :class="groupData.recommendation === 'review' ? 'border-amber-300' : 'border-red-300'"
    :data-automation-id="`duplicate-${entityKind}-group-${groupData.group_id}`"
  >
    <summary
      class="flex cursor-pointer list-none flex-col gap-3 p-4 hover:bg-slate-50 sm:flex-row sm:items-center sm:justify-between"
    >
      <div class="min-w-0">
        <div class="flex flex-wrap items-center gap-2">
          <span
            class="rounded-full px-2 py-0.5 text-xs font-semibold uppercase tracking-wide"
            :class="
              groupData.recommendation === 'review'
                ? 'bg-amber-100 text-amber-900'
                : 'bg-red-100 text-red-900'
            "
          >
            {{ groupData.recommendation }}
          </span>
          <span class="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-700">
            {{ entityLabel }}
          </span>
          <span class="text-sm text-slate-500">{{ groupData.members.length }} records</span>
        </div>
        <p class="mt-2 truncate font-semibold text-slate-900">{{ memberNames }}</p>
        <p class="mt-1 text-sm text-slate-600">{{ reasonSummary }}</p>
      </div>
      <ChevronDown
        class="h-5 w-5 shrink-0 text-slate-500 transition-transform group-open:rotate-180"
      />
    </summary>

    <div class="space-y-5 border-t border-slate-200 p-4">
      <div>
        <h3 class="text-xs font-semibold uppercase tracking-wide text-slate-500">Evidence</h3>
        <div class="mt-2 flex flex-wrap gap-2">
          <span
            v-for="item in groupData.evidence"
            :key="`${item.kind}-${item.normalized_value}`"
            class="rounded-md bg-indigo-50 px-2 py-1 text-xs text-indigo-900"
          >
            {{ evidenceKindLabel(item.kind) }}: {{ item.normalized_value }}
            <span class="text-indigo-600">({{ item.owner_count }})</span>
          </span>
          <span v-if="groupData.evidence.length === 0" class="text-sm text-slate-500">
            No shared contact detail recorded.
          </span>
        </div>
      </div>

      <div class="grid gap-3 lg:grid-cols-2">
        <article
          v-for="member in groupData.members"
          :key="memberId(member)"
          class="rounded-md border p-3"
          :class="isCanonical(member) ? 'border-indigo-300 bg-indigo-50/40' : 'border-slate-200'"
        >
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h3 class="font-semibold text-slate-900">{{ member.name }}</h3>
            <span
              v-if="isCanonical(member)"
              class="rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-semibold text-indigo-800"
            >
              Canonical
            </span>
          </div>

          <template v-if="entityKind === 'company'">
            <dl class="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              <dt class="text-slate-500">Email</dt>
              <dd class="break-all text-slate-800">{{ companyMember(member).email ?? '—' }}</dd>
              <dt class="text-slate-500">Address</dt>
              <dd class="text-slate-800">{{ companyMember(member).address ?? '—' }}</dd>
              <dt class="text-slate-500">Jobs</dt>
              <dd class="text-slate-800">{{ companyMember(member).job_count }}</dd>
              <dt class="text-slate-500">Contacts</dt>
              <dd class="text-slate-800">
                {{ companyMember(member).contact_names.join(', ') || '—' }}
              </dd>
              <dt class="text-slate-500">Roles</dt>
              <dd class="flex flex-wrap gap-1">
                <span v-if="companyMember(member).is_account_customer">Customer</span>
                <span v-if="companyMember(member).is_supplier">Supplier</span>
                <span v-if="companyMember(member).allow_jobs">Jobs enabled</span>
                <span v-if="companyMember(member).xero_archived">Xero archived</span>
                <span v-if="companyRoles(member).length === 0">—</span>
              </dd>
            </dl>
          </template>

          <template v-else>
            <dl class="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
              <dt class="text-slate-500">Email</dt>
              <dd class="break-all text-slate-800">{{ personMember(member).email ?? '—' }}</dd>
              <dt class="text-slate-500">Companies</dt>
              <dd class="text-slate-800">{{ companyNames(member) }}</dd>
              <dt class="text-slate-500">Contacts</dt>
              <dd class="text-slate-800">{{ personContacts(member) }}</dd>
              <dt class="text-slate-500">Activity</dt>
              <dd class="text-slate-800">
                {{ personMember(member).job_count }} jobs,
                {{ personMember(member).phone_call_count }} calls
              </dd>
              <dt class="text-slate-500">Status</dt>
              <dd class="text-slate-800">
                {{ personMember(member).is_active ? 'Active' : 'Inactive' }}
              </dd>
            </dl>
          </template>
        </article>
      </div>

      <p class="text-xs text-slate-400">Group {{ groupData.group_id }}</p>
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { z } from 'zod'
import { ChevronDown } from 'lucide-vue-next'

import { schemas } from '@/api/generated/api'

type CompanyGroup = z.infer<typeof schemas.DuplicateCompanyGroup>
type PersonGroup = z.infer<typeof schemas.DuplicatePersonGroup>
type CompanyMember = z.infer<typeof schemas.DuplicateCompanyMember>
type PersonMember = z.infer<typeof schemas.DuplicatePersonSummary>
type Group = CompanyGroup | PersonGroup
type Member = CompanyMember | PersonMember

const props = defineProps<{
  entityKind: 'company' | 'person'
  group: Group
}>()

const groupData = computed(() => props.group)
const entityLabel = computed(() => (props.entityKind === 'company' ? 'Company' : 'Person'))
const memberNames = computed(() => props.group.members.map((member) => member.name).join(' · '))
const reasonSummary = computed(() =>
  props.group.reason_codes.map((reason) => reason.replaceAll('_', ' ')).join(' · '),
)

const EVIDENCE_LABELS: Record<string, string> = {
  name: 'Name',
  email: 'Email',
  email_domain: 'Email domain',
  phone: 'Phone',
  address: 'Address',
  shared_person: 'Shared person',
}

function evidenceKindLabel(kind: string): string {
  return EVIDENCE_LABELS[kind] ?? kind.replaceAll('_', ' ')
}

function companyMember(member: Member): CompanyMember {
  if (!('company_id' in member)) throw new Error('Expected a company member')
  return member
}

function personMember(member: Member): PersonMember {
  if (!('person_id' in member)) throw new Error('Expected a person member')
  return member
}

function memberId(member: Member): string {
  return 'company_id' in member ? member.company_id : member.person_id
}

function isCanonical(member: Member): boolean {
  return memberId(member) === props.group.canonical_id
}

function companyRoles(member: Member): string[] {
  const company = companyMember(member)
  return [
    company.is_account_customer ? 'customer' : null,
    company.is_supplier ? 'supplier' : null,
    company.allow_jobs ? 'jobs' : null,
    company.xero_archived ? 'archived' : null,
  ].filter((role): role is string => role !== null)
}

function companyNames(member: Member): string {
  const names = personMember(member).company_links.map((link) => link.company_name)
  return names.join(', ') || '—'
}

function personContacts(member: Member): string {
  const methods = personMember(member).contact_methods.map(
    (method) => `${method.contact_label}: ${method.value}`,
  )
  return methods.join(', ') || '—'
}
</script>
