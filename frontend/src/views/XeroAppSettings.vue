<template>
  <AppLayout>
    <div class="p-4 sm:p-8">
      <div class="flex items-center justify-between mb-6">
        <h1 class="text-2xl font-bold">Xero Apps</h1>
        <Button @click="openCreateModal">
          <Plus class="w-4 h-4 mr-2" />
          Add app
        </Button>
      </div>

      <div v-if="loading && rows.length === 0" class="text-center py-10">
        <div class="flex items-center justify-center gap-2">
          <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-blue-500"></div>
          Loading Xero apps...
        </div>
      </div>

      <div
        v-else-if="error"
        class="bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded relative"
        role="alert"
      >
        <strong class="font-bold">Error:</strong>
        <span class="block sm:inline">{{ error }}</span>
      </div>

      <div v-else class="bg-white rounded-lg shadow overflow-hidden">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Label</TableHead>
              <TableHead>Client ID</TableHead>
              <TableHead class="text-center">Authorised</TableHead>
              <TableHead class="text-right">Day Remaining</TableHead>
              <TableHead class="text-center">Active</TableHead>
              <TableHead class="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <template v-if="rows.length > 0">
              <TableRow v-for="row in rows" :key="row.id">
                <TableCell class="font-medium">{{ row.label }}</TableCell>
                <TableCell class="font-mono text-xs">{{ truncate(row.client_id) }}</TableCell>
                <TableCell class="text-center">
                  <span v-if="row.has_tokens" class="text-green-600 font-bold">&#10003;</span>
                  <span v-else class="text-gray-400">&mdash;</span>
                </TableCell>
                <TableCell class="text-right font-mono text-sm">
                  {{ row.day_remaining ?? '—' }} / 5000
                </TableCell>
                <TableCell class="text-center">
                  <span
                    v-if="row.is_active"
                    class="inline-flex items-center rounded-full bg-indigo-100 px-2 py-0.5 text-xs font-medium text-indigo-800"
                  >
                    Active
                  </span>
                  <span v-else class="text-gray-400">&mdash;</span>
                </TableCell>
                <TableCell class="text-right">
                  <div class="flex justify-end gap-2">
                    <Button variant="outline" size="sm" @click="openEditModal(row)">Edit</Button>
                    <Button
                      v-if="!row.is_active"
                      variant="default"
                      size="sm"
                      @click="confirmActivate(row)"
                    >
                      Activate
                    </Button>
                    <Button
                      variant="destructive"
                      size="sm"
                      :disabled="row.is_active"
                      :title="row.is_active ? 'Cannot delete the active app' : 'Delete'"
                      @click="confirmDelete(row)"
                    >
                      Delete
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            </template>
            <template v-else>
              <TableRow>
                <TableCell colspan="6" class="text-center py-10 text-gray-500">
                  No Xero apps configured yet.
                </TableCell>
              </TableRow>
            </template>
          </TableBody>
        </Table>
      </div>
    </div>

    <!-- Create / Edit modal -->
    <Dialog v-if="isFormOpen" :open="true" @update:open="closeForm">
      <DialogContent class="sm:max-w-[525px]">
        <DialogHeader>
          <DialogTitle>{{ isEditing ? 'Edit Xero App' : 'Add Xero App' }}</DialogTitle>
          <DialogDescription>
            {{
              isEditing
                ? 'Update the credentials for this Xero app.'
                : 'Register a new Xero OAuth app.'
            }}
          </DialogDescription>
        </DialogHeader>

        <form @submit.prevent="onSubmit" class="grid gap-4 py-4">
          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="label" class="text-right">Label</Label>
            <div class="col-span-3">
              <Input id="label" v-model="form.label" required maxlength="64" />
            </div>
          </div>

          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="client_id" class="text-right">Client ID</Label>
            <div class="col-span-3">
              <Input id="client_id" v-model="form.client_id" required maxlength="128" />
            </div>
          </div>

          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="client_secret" class="text-right">Client Secret</Label>
            <div class="col-span-3">
              <Input
                id="client_secret"
                type="password"
                v-model="form.client_secret"
                :required="!isEditing"
                :placeholder="isEditing ? 'Leave blank to keep unchanged' : 'Enter client secret'"
              />
            </div>
          </div>

          <div class="grid grid-cols-4 items-center gap-4">
            <Label for="redirect_uri" class="text-right">Redirect URI</Label>
            <div class="col-span-3">
              <Input id="redirect_uri" v-model="form.redirect_uri" required maxlength="512" />
            </div>
          </div>

          <div
            v-if="credentialChangeWarning"
            class="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800"
          >
            Changing the client ID or secret will clear this app's tokens and quota. You'll need to
            log out of Xero and log back in to re-authorise.
          </div>

          <p v-if="formError" class="text-red-600 text-sm">{{ formError }}</p>

          <DialogFooter>
            <Button type="button" variant="outline" @click="closeForm">Cancel</Button>
            <Button type="submit" :disabled="isSubmitting">
              {{ isSubmitting ? 'Saving...' : 'Save' }}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>

    <!-- Activate confirm -->
    <Dialog v-if="isActivateOpen" :open="true" @update:open="closeActivate">
      <DialogContent class="sm:max-w-[525px]">
        <DialogHeader>
          <DialogTitle>Switch active Xero app</DialogTitle>
          <DialogDescription>
            Switch active Xero app from
            <span class="font-semibold">{{ activeApp?.label ?? 'none' }}</span>
            to
            <span class="font-semibold">{{ activateTarget?.label }}</span
            >? All sync jobs will start using
            <span class="font-semibold">{{ activateTarget?.label }}</span
            >'s credentials immediately.
          </DialogDescription>
        </DialogHeader>
        <div
          v-if="activateTarget && !activateTarget.has_tokens"
          class="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-sm text-amber-800"
        >
          This app has no tokens. After activating, you'll need to log out of Xero and log back in
          to authorise.
        </div>
        <DialogFooter>
          <Button variant="outline" @click="closeActivate">Cancel</Button>
          <Button variant="default" :disabled="isActivating" @click="doActivate">
            {{ isActivating ? 'Activating...' : 'Activate' }}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <!-- Delete confirm -->
    <ConfirmModal
      v-if="isDeleteOpen"
      title="Delete Xero app"
      :message="`Delete the Xero app '${deleteTarget?.label}'? This permanently removes its credentials and stored tokens.`"
      @confirm="doDelete"
      @close="closeDelete"
    />
  </AppLayout>
</template>

<script setup lang="ts">
import { ref, computed, reactive } from 'vue'
import { Plus } from 'lucide-vue-next'
import { toast } from 'vue-sonner'

import AppLayout from '@/components/AppLayout.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import ConfirmModal from '@/components/ConfirmModal.vue'

import { api } from '@/api/client'
import { useXeroApps, type XeroApp } from '@/composables/useXeroApps'

// Settings page handles its own refresh after mutations — no auto-poll needed.
const { rows, loading, error, refresh, activeApp } = useXeroApps(false)

const isFormOpen = ref(false)
const editingId = ref<string | null>(null)
const isSubmitting = ref(false)
const formError = ref<string | null>(null)

interface FormState {
  label: string
  client_id: string
  client_secret: string
  redirect_uri: string
}

const emptyForm: FormState = {
  label: '',
  client_id: '',
  client_secret: '',
  redirect_uri: '',
}

const form = reactive<FormState>({ ...emptyForm })
const originalClientId = ref<string>('')

const isEditing = computed<boolean>(() => editingId.value !== null)

const credentialChangeWarning = computed<boolean>(() => {
  if (!isEditing.value) {
    return false
  }
  if (form.client_secret.trim().length > 0) {
    return true
  }
  if (form.client_id !== originalClientId.value) {
    return true
  }
  return false
})

function truncate(value: string, max: number = 14): string {
  if (value.length <= max) {
    return value
  }
  return `${value.slice(0, max)}…`
}

function resetForm(): void {
  form.label = emptyForm.label
  form.client_id = emptyForm.client_id
  form.client_secret = emptyForm.client_secret
  form.redirect_uri = emptyForm.redirect_uri
  originalClientId.value = ''
  formError.value = null
}

function openCreateModal(): void {
  editingId.value = null
  resetForm()
  isFormOpen.value = true
}

function openEditModal(row: XeroApp): void {
  editingId.value = row.id
  form.label = row.label
  form.client_id = row.client_id
  form.client_secret = ''
  form.redirect_uri = row.redirect_uri
  originalClientId.value = row.client_id
  formError.value = null
  isFormOpen.value = true
}

function closeForm(): void {
  isFormOpen.value = false
  editingId.value = null
  resetForm()
}

async function onSubmit(): Promise<void> {
  formError.value = null
  isSubmitting.value = true
  try {
    if (isEditing.value && editingId.value) {
      // Only send changed credential fields; server clears tokens when they change.
      const payload: {
        label: string
        client_id: string
        redirect_uri: string
        client_secret?: string
      } = {
        label: form.label.trim(),
        client_id: form.client_id.trim(),
        redirect_uri: form.redirect_uri.trim(),
      }
      const secret = form.client_secret.trim()
      if (secret.length > 0) {
        payload.client_secret = secret
      }
      await api.workflow_xero_apps_partial_update(payload, {
        params: { id: editingId.value },
      })
      toast.success('Xero app updated.')
    } else {
      await api.workflow_xero_apps_create({
        label: form.label.trim(),
        client_id: form.client_id.trim(),
        client_secret: form.client_secret.trim(),
        redirect_uri: form.redirect_uri.trim(),
      })
      toast.success('Xero app created.')
    }
    closeForm()
    await refresh()
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to save Xero app.'
    formError.value = message
    toast.error('Failed to save Xero app.', { description: message })
  } finally {
    isSubmitting.value = false
  }
}

// Activate confirm flow
const isActivateOpen = ref(false)
const activateTarget = ref<XeroApp | null>(null)
const isActivating = ref(false)

function confirmActivate(row: XeroApp): void {
  activateTarget.value = row
  isActivateOpen.value = true
}

function closeActivate(): void {
  isActivateOpen.value = false
  activateTarget.value = null
}

async function doActivate(): Promise<void> {
  if (!activateTarget.value) {
    return
  }
  isActivating.value = true
  const target = activateTarget.value
  try {
    await api.workflow_xero_apps_activate_create(undefined, {
      params: { id: target.id },
    })
    toast.success(`'${target.label}' is now the active Xero app.`)
    closeActivate()
    await refresh()
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to activate Xero app.'
    toast.error('Failed to activate Xero app.', { description: message })
  } finally {
    isActivating.value = false
  }
}

// Delete confirm flow
const isDeleteOpen = ref(false)
const deleteTarget = ref<XeroApp | null>(null)

function confirmDelete(row: XeroApp): void {
  if (row.is_active) {
    return
  }
  deleteTarget.value = row
  isDeleteOpen.value = true
}

function closeDelete(): void {
  isDeleteOpen.value = false
  deleteTarget.value = null
}

async function doDelete(): Promise<void> {
  if (!deleteTarget.value) {
    return
  }
  const target = deleteTarget.value
  try {
    await api.workflow_xero_apps_destroy(undefined, { params: { id: target.id } })
    toast.success(`'${target.label}' deleted.`)
    closeDelete()
    await refresh()
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Failed to delete Xero app.'
    toast.error('Failed to delete Xero app.', { description: message })
  }
}
</script>
