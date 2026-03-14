<template>
  <Dialog :open="true" @update:open="handleClose">
    <DialogContent class="max-w-xl space-y-6 animate-in fade-in-0 zoom-in-95 ai-dialog-content">
      <DialogHeader>
        <DialogTitle>
          <span class="text-lg">Manage AI Providers</span>
          <i class="ml-2 text-indigo-600" aria-hidden="true">⚙️</i>
        </DialogTitle>
      </DialogHeader>
      <DialogDescription class="text-sm text-gray-500">
        Configure and manage your AI providers. Set default providers and ensure all fields are
        correctly filled.
      </DialogDescription>
      <div class="space-y-4 ai-providers-scroll">
        <div
          v-for="(provider, idx) in localProviders"
          :key="providerKey(provider, idx)"
          class="ai-provider-inline mx-auto"
        >
          <div class="flex flex-wrap gap-2 items-center w-full justify-center">
            <input
              v-model.trim="provider.name"
              @input="emitProviders"
              class="input ai-input"
              placeholder="Provider Name"
              autocomplete="off"
              autocorrect="off"
              spellcheck="false"
            />
            <input
              v-model.trim="provider.model_name"
              @input="emitProviders"
              class="input ai-input"
              placeholder="Model"
              autocomplete="off"
              autocorrect="off"
              spellcheck="false"
            />
            <select
              v-model="provider.provider_type"
              @change="emitProviders"
              class="input ai-input"
              autocomplete="off"
            >
              <option v-for="option in providerTypeOptions" :key="option" :value="option">
                {{ option }}
              </option>
            </select>
            <input
              :value="provider.api_key ?? ''"
              @input="onApiKeyInput(idx, $event)"
              class="input ai-input"
              :placeholder="provider.id ? 'Leave blank to keep current' : 'API Key *'"
              type="password"
              autocomplete="new-password"
              autocorrect="off"
              spellcheck="false"
            />
            <label class="flex items-center gap-1 whitespace-nowrap">
              <input
                type="checkbox"
                :checked="!!provider.default"
                @change="onDefaultChange(idx, $event)"
                class="mr-1"
              />
              Default
            </label>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              class="ai-remove-btn"
              @click="removeProvider(idx)"
              >Remove</Button
            >
          </div>
        </div>
      </div>
      <div class="flex gap-2 justify-end mt-4">
        <Button
          type="button"
          variant="outline"
          @click="addProvider"
          class="ai-close-btn flex items-center gap-1"
        >
          <span class="text-lg font-bold">+</span> Add Provider
        </Button>
        <Button
          type="button"
          variant="outline"
          @click="handleClose"
          class="ai-close-btn flex items-center gap-1"
        >
          <ArrowLeft class="w-4 h-4" /> Close
        </Button>
      </div>
    </DialogContent>
  </Dialog>
</template>

<script setup lang="ts">
import { debugLog } from '@/utils/debug'

import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from './ui/dialog'
import Button from './ui/button/Button.vue'
import { ref, watch } from 'vue'
import { ArrowLeft } from 'lucide-vue-next'
import { schemas } from '@/api/generated/api'
import { z } from 'zod'

type AIProvider = z.infer<typeof schemas.AIProvider>
type ProviderForm = z.infer<typeof schemas.AIProviderCreateUpdateRequest> & {
  id?: AIProvider['id']
}

const props = defineProps<{ providers?: AIProvider[] }>()
const emit = defineEmits(['close', 'update:providers'])

const providerTypeOptions = schemas.ProviderTypeEnum.options

const createLocalProvider = (provider?: AIProvider): ProviderForm => ({
  id: provider?.id,
  name: provider?.name ?? '',
  provider_type: provider?.provider_type ?? providerTypeOptions[0],
  model_name: provider?.model_name ?? '',
  default: provider?.default ?? false,
  api_key: '',
})

const toLocalProviders = (providers?: AIProvider[]) =>
  (providers ?? []).map((provider) => createLocalProvider(provider))

const localProviders = ref<ProviderForm[]>(toLocalProviders(props.providers))

debugLog('[AIProvidersDialog] props.providers:', props.providers)
debugLog('[AIProvidersDialog] local providers:', localProviders.value)
debugLog('[AIProvidersDialog] localProviders.value.length:', localProviders.value.length)

if (props.providers && props.providers.length > 0) {
  debugLog('[AIProvidersDialog] First provider:', props.providers[0])
}

watch(
  () => props.providers,
  (newVal) => {
    localProviders.value = toLocalProviders(newVal)
  },
  { deep: true },
)

const providerKey = (provider: ProviderForm, idx: number) => provider.id ?? idx

const onApiKeyInput = (idx: number, event: Event) => {
  const input = event.target as HTMLInputElement | null
  const provider = localProviders.value[idx]
  if (!input || !provider) return

  const trimmed = input.value.trim()
  input.value = trimmed
  provider.api_key = trimmed
  emitProviders()
}

const onDefaultChange = (idx: number, event: Event) => {
  const checkbox = event.target as HTMLInputElement | null
  if (!checkbox) return
  setDefault(idx, checkbox.checked)
}

function handleClose() {
  debugLog(
    '[AIProvidersDialog] handleClose - final localProviders:',
    localProviders.value.map((p) => ({
      name: p.name,
      default: p.default,
      id: p.id,
    })),
  )

  emitProviders()
  emit('close')
}

function addProvider() {
  localProviders.value.push(createLocalProvider())
  debugLog('[AIProvidersDialog] addProvider - new provider added')
  emitProviders()
}

function removeProvider(idx: number) {
  if (!localProviders.value[idx]) return
  localProviders.value.splice(idx, 1)
  debugLog('[AIProvidersDialog] removeProvider - provider removed at index:', idx)
  emitProviders()
}

function setDefault(idx: number, checked: boolean) {
  const provider = localProviders.value[idx]
  if (!provider) return
  debugLog(`[AIProvidersDialog] setDefault called for idx: ${idx}, checked: ${checked}`)
  debugLog(`[AIProvidersDialog] Provider BEFORE setDefault:`, {
    name: provider.name,
    default: provider.default,
  })

  if (checked) {
    localProviders.value.forEach((p, i) => {
      debugLog(`[AIProvidersDialog] Setting provider ${i} default to ${i === idx}`)
      p.default = i === idx
    })
  } else {
    debugLog(`[AIProvidersDialog] Unchecking provider ${idx}`)
    provider.default = false
  }

  debugLog(`[AIProvidersDialog] Provider AFTER setDefault:`, {
    name: provider.name,
    default: provider.default,
  })
  debugLog(
    '[AIProvidersDialog] All providers after setDefault:',
    localProviders.value.map((p) => ({ name: p.name, default: p.default })),
  )

  emitProviders()
}

const getTrimmedApiKey = (value: unknown): string | undefined => {
  if (typeof value !== 'string') return undefined
  const trimmed = value.trim()
  return trimmed.length ? trimmed : undefined
}

function emitProviders() {
  const providersToSend = localProviders.value.map((provider) => {
    const payload: ProviderForm = {
      ...provider,
      default: !!provider.default,
    }

    const apiKey = getTrimmedApiKey(provider.api_key)

    if (!payload.id && !apiKey) {
      console.warn('New provider without API key:', payload)
    }

    if (apiKey) {
      payload.api_key = apiKey
    } else {
      delete payload.api_key
    }

    return payload
  })

  debugLog('[AIProvidersDialog] emitProviders, sending providers count:', providersToSend.length)
  debugLog(
    '[AIProvidersDialog] emitProviders, default values:',
    providersToSend.map((p) => ({
      name: p.name,
      default: p.default,
      hasApiKey: !!p.api_key,
      apiKeyLength: p.api_key?.length ?? 0,
    })),
  )

  emit('update:providers', providersToSend)
}
</script>

<style scoped>
.input {
  padding: 0.5rem 0.75rem;
  border: 1px solid #c7d2fe;
  border-radius: 0.5rem;
  background: #f8fafc;
  font-size: 0.875rem;
  transition:
    border 0.2s,
    box-shadow 0.2s;
}
.input:focus {
  border-color: #6366f1;
  outline: none;
  box-shadow: 0 0 0 2px #a5b4fc66;
}
.ai-provider-inline {
  background: linear-gradient(90deg, #e0e7ff 0%, #f1f5f9 100%);
  border-radius: 0.75rem;
  box-shadow: 0 2px 12px 0 rgba(80, 80, 120, 0.08);
  padding: 1rem 1.25rem;
  margin-bottom: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  transition:
    box-shadow 0.2s,
    transform 0.2s;
  position: relative;
  overflow-x: auto;
  max-width: 700px;
}
.ai-provider-inline:hover {
  box-shadow: 0 4px 24px 0 rgba(80, 80, 120, 0.13);
  transform: scale(1.01);
}
.ai-input {
  min-width: 90px;
  max-width: 160px;
  flex: 1 1 120px;
  margin-right: 0.5rem;
  background: #f8fafc;
}
.ai-remove-btn {
  color: #a21caf;
  background: transparent;
  border-radius: 0.5rem;
  transition:
    background 0.2s,
    color 0.2s;
}
.ai-remove-btn:hover {
  background: #f3e8ff;
  color: #7c3aed;
}
.ai-add-btn {
  background: linear-gradient(90deg, #c7d2fe 0%, #e0e7ff 100%);
  color: #3730a3;
  border-radius: 0.5rem;
  font-weight: 600;
  box-shadow: 0 1px 4px 0 rgba(80, 80, 120, 0.08);
  transition:
    background 0.2s,
    color 0.2s;
}
.ai-add-btn:hover {
  background: linear-gradient(90deg, #a5b4fc 0%, #c7d2fe 100%);
  color: #312e81;
}
.ai-close-btn {
  min-width: 100px;
  border-radius: 0.5rem;
  font-weight: 500;
  background: linear-gradient(90deg, #f1f5f9 0%, #e0e7ff 100%);
  color: #3730a3;
  box-shadow: 0 1px 4px 0 rgba(80, 80, 120, 0.08);
  transition:
    background 0.2s,
    color 0.2s;
}
.ai-close-btn:hover {
  background: linear-gradient(90deg, #c7d2fe 0%, #a5b4fc 100%);
  color: #312e81;
}
.dialog-content {
  animation: fadeIn 0.5s;
}
@keyframes fadeIn {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
.ai-dialog-content {
  max-height: 80vh;
  min-width: 340px;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
}
.ai-providers-scroll {
  max-height: 45vh;
  overflow-y: auto;
  padding-right: 2px;
  margin-bottom: 0.5rem;
}
@media (max-width: 600px) {
  .ai-dialog-content {
    min-width: 0;
    max-width: 98vw;
    padding: 0.5rem;
  }
  .ai-provider-inline {
    padding: 0.5rem 0.5rem;
    max-width: 98vw;
  }
  .ai-input {
    min-width: 70px;
    max-width: 110px;
    font-size: 0.8rem;
  }
}
</style>
