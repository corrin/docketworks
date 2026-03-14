<template>
  <Dialog :open="true" @update:open="handleClose">
    <DialogContent
      class="max-w-2xl space-y-6 animate-in fade-in-0 zoom-in-95"
      data-automation-id="StaffFormModal-container"
    >
      <DialogHeader>
        <DialogTitle>{{ staff ? 'Edit Staff' : 'New Staff' }}</DialogTitle>
      </DialogHeader>
      <form @submit.prevent="submitForm" class="space-y-4">
        <!-- Tab Navigation -->
        <div class="flex border-b mb-2 gap-2">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            type="button"
            :class="[
              'px-4 py-2 font-medium',
              activeTab === tab.key
                ? 'border-b-2 border-indigo-600 text-indigo-700'
                : 'text-gray-500',
            ]"
            @click="activeTab = tab.key"
          >
            <span v-if="tab.icon" :class="'mr-2'">
              <component :is="tab.icon" class="inline w-4 h-4 align-text-bottom" />
            </span>
            {{ tab.label }}
          </button>
        </div>
        <!-- Tab Content -->
        <div v-show="activeTab === 'personal'" class="space-y-2">
          <div class="flex gap-2">
            <div class="w-1/2">
              <label class="block text-sm font-medium mb-1" for="first_name">First Name</label>
              <Input
                id="first_name"
                v-model="form.first_name"
                placeholder="First Name"
                data-automation-id="StaffFormModal-first-name"
                required
              />
            </div>
            <div class="w-1/2">
              <label class="block text-sm font-medium mb-1" for="last_name">Last Name</label>
              <Input
                id="last_name"
                v-model="form.last_name"
                placeholder="Last Name"
                data-automation-id="StaffFormModal-last-name"
                required
              />
            </div>
          </div>
          <div class="flex gap-2">
            <div class="w-1/2">
              <label class="block text-sm font-medium mb-1" for="preferred_name"
                >Preferred Name</label
              >
              <Input
                id="preferred_name"
                v-model="form.preferred_name"
                placeholder="Preferred Name"
              />
            </div>
            <div class="w-1/2">
              <label class="block text-sm font-medium mb-1" for="email">E-mail</label>
              <Input
                id="email"
                v-model="form.email"
                type="email"
                placeholder="E-mail"
                data-automation-id="StaffFormModal-email"
                required
              />
            </div>
          </div>
          <div class="flex gap-2">
            <div class="w-1/2">
              <label class="block text-sm font-medium mb-1" for="password">Password</label>
              <Input
                id="password"
                v-model="form.password"
                type="password"
                placeholder="Password"
                data-automation-id="StaffFormModal-password"
                :required="!props.staff"
              />
            </div>
            <div class="w-1/2">
              <label class="block text-sm font-medium mb-1" for="password_confirmation"
                >Confirm Password</label
              >
              <Input
                id="password_confirmation"
                v-model="form.password_confirmation"
                type="password"
                placeholder="Confirm Password"
                data-automation-id="StaffFormModal-password-confirm"
                :required="!props.staff"
                :class="{ 'border-red-500 focus:ring-red-500': passwordMismatch }"
              />
              <p v-if="passwordMismatch" class="text-sm text-red-600 mt-1">
                Passwords do not match
              </p>
            </div>
          </div>
          <div class="flex gap-2">
            <div class="w-1/3">
              <label class="block text-sm font-medium mb-1" for="base_wage_rate"
                >Base Wage Rate (NZD/hour)</label
              >
              <Input
                id="base_wage_rate"
                v-model="form.base_wage_rate"
                type="number"
                placeholder="Base Wage Rate"
                min="0"
                step="0.01"
              />
            </div>
            <div class="w-1/3">
              <label class="block text-sm font-medium mb-1">Costing Rate (NZD/hour)</label>
              <Input
                :model-value="staff?.wage_rate ?? '—'"
                type="text"
                disabled
                class="bg-gray-100 text-gray-500"
              />
            </div>
            <div class="w-1/3">
              <label class="block text-sm font-medium mb-1" for="xero_user_id">Xero User ID</label>
              <Input id="xero_user_id" v-model="form.xero_user_id" placeholder="Xero User ID" />
            </div>
          </div>
          <div class="flex justify-center mt-2">
            <div>
              <label class="block text-sm font-medium mb-1 text-center">Profile Icon/Image</label>
              <label
                class="relative group cursor-pointer"
                tabindex="0"
                @keydown.enter.prevent="avatarInput?.click()"
                :aria-label="
                  form.first_name || form.last_name
                    ? `${form.first_name} ${form.last_name}`
                    : 'User avatar'
                "
              >
                <div
                  class="avatar-upload flex items-center justify-center rounded-full bg-indigo-100 border-2 border-indigo-300 w-16 h-16 text-xl font-bold text-indigo-700 overflow-hidden transition-all duration-150 group-hover:ring-4 group-hover:ring-indigo-300 group-hover:opacity-90 mx-auto"
                >
                  <template v-if="iconUrl">
                    <img :src="iconUrl" alt="Profile image" class="object-cover w-full h-full" />
                  </template>
                  <template v-else>
                    {{ initials }}
                  </template>
                  <div
                    class="absolute inset-0 flex flex-col items-center justify-center bg-indigo-900/60 opacity-0 group-hover:opacity-100 transition-opacity duration-150 z-10"
                  >
                    <svg
                      class="w-6 h-6 text-white mb-1"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        d="M12 16v-4m0 0V8m0 4h4m-4 0H8"
                        stroke-width="2"
                        stroke-linecap="round"
                        stroke-linejoin="round"
                      />
                    </svg>
                    <span class="text-xs text-white">Change</span>
                  </div>
                </div>
                <input
                  ref="avatarInput"
                  type="file"
                  accept="image/*"
                  class="hidden"
                  @change="onFileChange"
                />
              </label>
            </div>
          </div>
        </div>
        <div v-show="activeTab === 'working'" class="space-y-2">
          <div class="grid grid-cols-2 gap-2">
            <div>
              <label class="block text-sm font-medium mb-1" for="hours_mon">Monday Hours</label>
              <Input
                id="hours_mon"
                v-model.number="form.hours_mon"
                type="number"
                min="0"
                max="24"
                step="0.25"
                placeholder="Monday Hours"
              />
            </div>
            <div>
              <label class="block text-sm font-medium mb-1" for="hours_tue">Tuesday Hours</label>
              <Input
                id="hours_tue"
                v-model.number="form.hours_tue"
                type="number"
                min="0"
                max="24"
                step="0.25"
                placeholder="Tuesday Hours"
              />
            </div>
            <div>
              <label class="block text-sm font-medium mb-1" for="hours_wed">Wednesday Hours</label>
              <Input
                id="hours_wed"
                v-model.number="form.hours_wed"
                type="number"
                min="0"
                max="24"
                step="0.25"
                placeholder="Wednesday Hours"
              />
            </div>
            <div>
              <label class="block text-sm font-medium mb-1" for="hours_thu">Thursday Hours</label>
              <Input
                id="hours_thu"
                v-model.number="form.hours_thu"
                type="number"
                min="0"
                max="24"
                step="0.25"
                placeholder="Thursday Hours"
              />
            </div>
            <div>
              <label class="block text-sm font-medium mb-1" for="hours_fri">Friday Hours</label>
              <Input
                id="hours_fri"
                v-model.number="form.hours_fri"
                type="number"
                min="0"
                max="24"
                step="0.25"
                placeholder="Friday Hours"
              />
            </div>
            <div>
              <label class="block text-sm font-medium mb-1" for="hours_sat">Saturday Hours</label>
              <Input
                id="hours_sat"
                v-model.number="form.hours_sat"
                type="number"
                min="0"
                max="24"
                step="0.25"
                placeholder="Saturday Hours"
              />
            </div>
            <div>
              <label class="block text-sm font-medium mb-1" for="hours_sun">Sunday Hours</label>
              <Input
                id="hours_sun"
                v-model.number="form.hours_sun"
                type="number"
                min="0"
                max="24"
                step="0.25"
                placeholder="Sunday Hours"
              />
            </div>
          </div>
        </div>
        <div v-show="activeTab === 'permissions'" class="space-y-2">
          <div class="flex gap-2 items-center">
            <label class="flex items-center gap-2"
              ><input type="checkbox" v-model="form.is_office_staff" /> Staff</label
            >
            <label class="flex items-center gap-2"
              ><input type="checkbox" v-model="form.is_superuser" /> Superuser</label
            >
          </div>
          <div>
            <label class="block text-sm font-medium mb-1" for="groups"
              >Groups (IDs, comma separated)</label
            >
            <Input id="groups" v-model="form.groups" placeholder="Group IDs (comma separated)" />
          </div>
          <div>
            <label class="block text-sm font-medium mb-1" for="user_permissions"
              >Permissions (IDs, comma separated)</label
            >
            <Input
              id="user_permissions"
              v-model="form.user_permissions"
              placeholder="Permission IDs (comma separated)"
            />
          </div>
        </div>
        <DialogFooter class="flex gap-2 justify-end">
          <Button variant="ghost" type="button" @click="handleClose" :disabled="isLoading"
            >Cancel</Button
          >
          <Button type="submit" :disabled="isLoading" data-automation-id="StaffFormModal-submit">
            <div v-if="isLoading" class="flex items-center gap-2">
              <div class="animate-spin rounded-full h-4 w-4 border-b-2 border-white"></div>
              {{ staff ? 'Saving...' : 'Creating...' }}
            </div>
            <span v-else>{{ staff ? 'Save Changes' : 'Create Staff' }}</span>
          </Button>
        </DialogFooter>
      </form>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import Dialog from '@/components/ui/dialog/Dialog.vue'
import DialogContent from '@/components/ui/dialog/DialogContent.vue'
import DialogHeader from '@/components/ui/dialog/DialogHeader.vue'
import DialogTitle from '@/components/ui/dialog/DialogTitle.vue'
import DialogFooter from '@/components/ui/dialog/DialogFooter.vue'
import Button from '@/components/ui/button/Button.vue'
import Input from '@/components/ui/input/Input.vue'
import { computed, ref, watch } from 'vue'
import { z } from 'zod'
import { schemas } from '../api/generated/api'
import { useStaffApi } from '@/composables/useStaffApi'
import { UserIcon, LockIcon, ClockIcon } from 'lucide-vue-next'
import { toast } from 'vue-sonner'
import { normalizeOptionalString } from '@/utils/sanitize'

type Staff = z.infer<typeof schemas.Staff>

const createStaffSchema = schemas.StaffCreateRequest.extend({
  password: z.string().min(8, 'Password must be at least 8 characters'),
  password_confirmation: z.string().min(1, 'Please confirm your password'),
}).refine((data) => data.password === data.password_confirmation, {
  message: "Passwords don't match",
  path: ['password_confirmation'],
})

const updateStaffSchema = schemas.PatchedStaffRequest.extend({
  password: z.string().min(8, 'Password must be at least 8 characters').optional(),
  password_confirmation: z.string().optional(),
}).refine(
  (data) => {
    if (data.password || data.password_confirmation) {
      return data.password === data.password_confirmation
    }
    return true
  },
  {
    message: "Passwords don't match",
    path: ['password_confirmation'],
  },
)

const tabs = [
  { key: 'personal', label: 'Personal Info', icon: UserIcon },
  { key: 'working', label: 'Working Hours', icon: ClockIcon },
  { key: 'permissions', label: 'Permissions', icon: LockIcon },
]
const activeTab = ref('personal')

const props = defineProps<{ staff: Staff | null }>()
const emit = defineEmits(['close', 'saved'])

const isLoading = ref(false)
const avatarInput = ref<HTMLInputElement | null>(null)
const { createStaff, updateStaff } = useStaffApi()
const form = ref({
  first_name: '',
  last_name: '',
  preferred_name: '',
  email: '',
  password: '',
  password_confirmation: '',
  base_wage_rate: 0,
  xero_user_id: '',
  icon: null as File | null,
  hours_mon: 0,
  hours_tue: 0,
  hours_wed: 0,
  hours_thu: 0,
  hours_fri: 0,
  hours_sat: 0,
  hours_sun: 0,
  is_office_staff: false,
  is_superuser: false,
  groups: '',
  user_permissions: '',
  last_login: '',
  date_joined: '',
})
const error = ref('')

const iconUrl = computed(() => {
  if (form.value.icon) {
    return URL.createObjectURL(form.value.icon)
  }
  if (props.staff && props.staff.icon_url) {
    return props.staff.icon_url
  }
  return null
})

const initials = computed(() => {
  const first = form.value.first_name?.trim()[0] || ''
  const last = form.value.last_name?.trim()[0] || ''
  return (first + last).toUpperCase() || 'U'
})

const passwordMismatch = computed(() => {
  if (!form.value.password && !form.value.password_confirmation) {
    return false
  }
  return form.value.password !== form.value.password_confirmation
})

watch(
  () => props.staff,
  (staff) => {
    console.log('StaffFormModal - Props staff changed:', staff)
    if (staff) {
      console.log(
        'StaffFormModal - Staff base_wage_rate from props:',
        staff.base_wage_rate,
        typeof staff.base_wage_rate,
      )
      form.value = {
        first_name: staff.first_name,
        last_name: staff.last_name,
        preferred_name: staff.preferred_name || '',
        email: staff.email,
        password: '',
        password_confirmation: '',
        base_wage_rate: staff.base_wage_rate || 0,
        xero_user_id: staff.xero_user_id || '',
        icon: null,
        hours_mon: staff.hours_mon || 0,
        hours_tue: staff.hours_tue || 0,
        hours_wed: staff.hours_wed || 0,
        hours_thu: staff.hours_thu || 0,
        hours_fri: staff.hours_fri || 0,
        hours_sat: staff.hours_sat || 0,
        hours_sun: staff.hours_sun || 0,
        is_office_staff: staff.is_office_staff || false,
        is_superuser: staff.is_superuser || false,
        // Convert arrays of numbers to comma-separated strings for form fields
        groups:
          Array.isArray(staff.groups) && staff.groups.length > 0 ? staff.groups.join(', ') : '',
        user_permissions:
          Array.isArray(staff.user_permissions) && staff.user_permissions.length > 0
            ? staff.user_permissions.join(', ')
            : '',
        last_login: staff.last_login || '',
        date_joined: staff.date_joined || '',
      }
      console.log('StaffFormModal - Form populated with:', form.value)
      console.log(
        'StaffFormModal - Form base_wage_rate after parsing:',
        form.value.base_wage_rate,
        typeof form.value.base_wage_rate,
      )
    } else {
      form.value = {
        first_name: '',
        last_name: '',
        preferred_name: '',
        email: '',
        password: '',
        password_confirmation: '',
        base_wage_rate: 0,
        xero_user_id: '',
        icon: null,
        hours_mon: 0,
        hours_tue: 0,
        hours_wed: 0,
        hours_thu: 0,
        hours_fri: 0,
        hours_sat: 0,
        hours_sun: 0,
        is_office_staff: false,
        is_superuser: false,
        groups: '',
        user_permissions: '',
        last_login: '',
        date_joined: '',
      }
    }
    error.value = ''
  },
  { immediate: true },
)

function onFileChange(e: Event) {
  const files = (e.target as HTMLInputElement).files
  form.value.icon = files && files.length ? files[0] : null
}

function handleClose() {
  emit('close')
}

async function submitForm() {
  error.value = ''
  isLoading.value = true

  console.log('StaffFormModal - Submitting form with data:', form.value)
  console.log(
    'StaffFormModal - Form base_wage_rate before validation:',
    form.value.base_wage_rate,
    typeof form.value.base_wage_rate,
  )

  // Prepare base data - shared between validation and API call
  const lastLogin = normalizeOptionalString(form.value.last_login)
  const dateJoined = normalizeOptionalString(form.value.date_joined)
  const preferredName = normalizeOptionalString(form.value.preferred_name)
  const xeroUserId = normalizeOptionalString(form.value.xero_user_id)

  const baseData: Record<string, unknown> = {
    first_name: form.value.first_name.trim(),
    last_name: form.value.last_name.trim(),
    email: form.value.email.trim(),
    base_wage_rate: form.value.base_wage_rate,
    is_office_staff: form.value.is_office_staff,
    is_superuser: form.value.is_superuser,
    hours_mon: form.value.hours_mon,
    hours_tue: form.value.hours_tue,
    hours_wed: form.value.hours_wed,
    hours_thu: form.value.hours_thu,
    hours_fri: form.value.hours_fri,
    hours_sat: form.value.hours_sat,
    hours_sun: form.value.hours_sun,
    // Convert groups and user_permissions from strings to arrays
    groups:
      form.value.groups && form.value.groups.trim()
        ? form.value.groups
            .trim()
            .split(',')
            .map((g) => Number(g.trim()))
            .filter((g) => !isNaN(g))
        : [],
    user_permissions:
      form.value.user_permissions && form.value.user_permissions.trim()
        ? form.value.user_permissions
            .trim()
            .split(',')
            .map((p) => Number(p.trim()))
            .filter((p) => !isNaN(p))
        : [],
    // Handle optional fields - only include if they have a value
    ...(preferredName && { preferred_name: preferredName }),
    ...(xeroUserId && { xero_user_id: xeroUserId }),
    ...(lastLogin && { last_login: lastLogin }),
    ...(dateJoined && { date_joined: dateJoined }),
  }

  // Add password if provided
  if (form.value.password) {
    baseData.password = form.value.password
  }

  // Validation data includes password_confirmation
  const validationData = {
    ...baseData,
    ...(form.value.password_confirmation && {
      password_confirmation: form.value.password_confirmation,
    }),
  }

  const schema = props.staff ? updateStaffSchema : createStaffSchema
  const parsed = schema.safeParse(validationData)

  console.log('StaffFormModal - Schema validation result:', parsed)

  if (!parsed.success) {
    error.value = parsed.error.errors[0].message
    console.error('StaffFormModal - Validation failed:', parsed.error.errors)
    isLoading.value = false
    return
  }
  try {
    // API data is baseData (password already included if provided, no password_confirmation)
    const apiData = { ...baseData }

    // Include icon for create operations
    if (!props.staff && form.value.icon) {
      apiData.icon = form.value.icon
    }

    console.log('StaffFormModal - API data being sent:', apiData)

    if (props.staff) {
      await updateStaff(props.staff.id, apiData)
      toast.success('Staff member updated successfully!')
    } else {
      await createStaff(apiData as z.infer<typeof schemas.StaffCreateRequest>)
      toast.success('Staff member created successfully!')
    }
    emit('saved')
  } catch (e) {
    console.error('StaffFormModal - Save error:', e)
    if (e instanceof Error) {
      // Extract meaningful error message from API response
      let errorMessage = 'Failed to save staff member.'
      if (e.message.includes('400') && e.message.includes('AxiosError')) {
        // Try to extract specific validation errors from the response
        const response = (e as Error & { response?: { data?: Record<string, string | string[]> } })
          .response
        if (response?.data) {
          const errors = Object.entries(response.data)
            .map(([field, messages]) => {
              const fieldName = field.charAt(0).toUpperCase() + field.slice(1).replace('_', ' ')
              const errorMessages = Array.isArray(messages) ? messages.join(', ') : messages
              return `${fieldName}: ${errorMessages}`
            })
            .join('\n')
          errorMessage = `Validation errors:\n${errors}`
        }
      } else {
        errorMessage = e.message
      }
      toast.error(errorMessage)
    } else {
      toast.error('Failed to save staff member.')
    }
  } finally {
    isLoading.value = false
  }
}
</script>

<style scoped>
.animate-in {
  animation: fadeInZoom 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

@keyframes fadeInZoom {
  from {
    opacity: 0;
    transform: scale(0.95);
  }

  to {
    opacity: 1;
    transform: scale(1);
  }
}

.avatar-upload {
  position: relative;
  width: 6rem;
  height: 6rem;
  border-radius: 9999px;
  background: #e0e7ff;
  border: 2px solid #a5b4fc;
  color: #3730a3;
  font-size: 2rem;
  font-weight: 700;
  overflow: hidden;
  transition:
    box-shadow 0.2s,
    border 0.2s;
  cursor: pointer;
}

.avatar-upload img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}

.avatar-upload:focus {
  outline: 2px solid #6366f1;
  outline-offset: 2px;
}
</style>
