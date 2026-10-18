import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import {
  aiProvidersListOptions,
  aiProvidersListQueryKey,
  aiProvidersCreateMutation,
  aiProvidersPartialUpdateMutation,
  aiProvidersDestroyMutation,
  aiProvidersSetDefaultMutation,
  aiProvidersTestMutation,
  apiErrorMessage,
  zAiProviderTypes,
  type ProviderOut,
  type ProviderPatch,
  type AiProviderTypes,
} from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog'
import { ListTable } from '@/features/shared/ListTable'
import { useUnsavedChangesGuard } from '@/features/shared/useUnsavedChangesGuard'
import { SecretField, type SecretDraft } from './IntegrationSecretField'

const PROVIDER_COLUMNS = ['name', 'vendor', 'model', 'apiKey', 'default', 'actions'] as const

export function AIProvidersSection() {
  const { t } = useTranslation('admin')
  const providers = useQuery(aiProvidersListOptions())
  const queryClient = useQueryClient()
  const remove = useMutation(aiProvidersDestroyMutation())
  const choose = useMutation(aiProvidersSetDefaultMutation())
  const test = useMutation(aiProvidersTestMutation())
  const [editing, setEditing] = useState<ProviderOut | null | undefined>(undefined)
  const pending = remove.isPending || choose.isPending || test.isPending

  async function act(provider: ProviderOut, action: 'delete' | 'default' | 'test') {
    if (
      action === 'delete' &&
      !window.confirm(
        provider.default
          ? t('aiProviders.confirmDeleteDefault', { name: provider.name })
          : t('aiProviders.confirmDelete', { name: provider.name }),
      )
    )
      return
    try {
      const options = { path: { provider_id: provider.id } }
      if (action === 'delete') {
        await remove.mutateAsync(options)
        toast.success(t('aiProviders.deleted'))
      } else if (action === 'default') {
        await choose.mutateAsync(options)
        toast.success(t('aiProviders.madeDefault', { name: provider.name }))
      } else {
        const result = await test.mutateAsync(options)
        toast.success(t('aiProviders.testSucceeded', { model: result.model }))
      }
      await queryClient.invalidateQueries({ queryKey: aiProvidersListQueryKey() })
    } catch (error) {
      toast.error(apiErrorMessage(error, t('aiProviders.actionFailed')))
    }
  }

  return (
    <section className="space-y-4" data-automation-id="AIProviders-root">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t('aiProviders.title')}</h2>
          <p className="text-sm text-slate-500">{t('aiProviders.intro')}</p>
          {providers.data && (
            <p className="text-sm text-slate-500">
              {t('aiProviders.providerCount', { total: providers.data.length })}
              {providers.data.some((row) => row.default) ? '' : t('aiProviders.noDefault')}
            </p>
          )}
        </div>
        <Button onClick={() => setEditing(null)} data-automation-id="AIProviders-add">
          {t('aiProviders.add')}
        </Button>
      </header>
      <ListTable
        isPending={providers.isPending}
        isError={providers.isError}
        onRetry={() => void providers.refetch()}
        loadingLabel={t('aiProviders.loading')}
        errorLabel={apiErrorMessage(providers.error, t('aiProviders.loadFailed'))}
        rows={providers.data}
        emptyLabel={t('aiProviders.empty')}
        automationId="AIProviders-table"
        wrapperClassName="max-h-96"
        head={
          <tr>
            {PROVIDER_COLUMNS.map((column) => (
              <th key={column} className="p-2 text-left font-medium">
                {t(`aiProviders.columns.${column}`)}
              </th>
            ))}
          </tr>
        }
        renderRow={(provider) => (
          <tr
            key={provider.id}
            className="border-t"
            data-automation-id={`AIProviders-row-${provider.id}`}
          >
            <td className="p-2">{provider.name}</td>
            <td className="p-2">{provider.provider_type}</td>
            <td className="p-2">{provider.model_name ?? t('aiProviders.notConfigured')}</td>
            <td className="p-2">
              {provider.has_api_key ? t('aiProviders.configured') : t('aiProviders.notConfigured')}
            </td>
            <td className="p-2">
              <input
                type="radio"
                name="application-ai-default"
                aria-label={t('aiProviders.useAsDefaultAria', { name: provider.name })}
                checked={provider.default}
                disabled={pending || !provider.has_api_key || provider.model_name === null}
                onChange={() => void act(provider, 'default')}
              />
            </td>
            <td className="p-2">
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pending}
                  onClick={() => setEditing(provider)}
                >
                  {t('aiProviders.edit')}
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={pending || !provider.has_api_key || provider.model_name === null}
                  onClick={() => void act(provider, 'test')}
                >
                  {t('aiProviders.test')}
                </Button>
                <Button
                  size="sm"
                  variant="destructive"
                  disabled={pending}
                  onClick={() => void act(provider, 'delete')}
                >
                  {t('aiProviders.delete')}
                </Button>
              </div>
            </td>
          </tr>
        )}
      />
      <p className="text-xs text-slate-500">{t('aiProviders.testHint')}</p>
      {editing !== undefined && (
        <ProviderDialog provider={editing} onClose={() => setEditing(undefined)} />
      )}
    </section>
  )
}

function ProviderDialog({
  provider,
  onClose,
}: {
  provider: ProviderOut | null
  onClose: () => void
}) {
  const { t } = useTranslation('admin')
  const queryClient = useQueryClient()
  const create = useMutation(aiProvidersCreateMutation())
  const update = useMutation(aiProvidersPartialUpdateMutation())
  const [name, setName] = useState(provider?.name ?? '')
  const [vendor, setVendor] = useState<AiProviderTypes>(provider?.provider_type ?? 'OpenAI')
  const [model, setModel] = useState(provider?.model_name ?? '')
  const [key, setKey] = useState<SecretDraft>(undefined)
  const [error, setError] = useState<string | null>(null)
  const dirty =
    name !== (provider?.name ?? '') ||
    vendor !== (provider?.provider_type ?? 'OpenAI') ||
    model !== (provider?.model_name ?? '') ||
    key !== undefined
  const saving = create.isPending || update.isPending
  useUnsavedChangesGuard(dirty)

  function close() {
    if (saving) return
    if (dirty && !window.confirm(t('aiProviderDialog.confirmDiscard'))) return
    onClose()
  }

  async function save(event: React.FormEvent) {
    event.preventDefault()
    setError(null)
    try {
      if (provider === null) {
        if (typeof key !== 'string' || key.trim() === '' || model.trim() === '') {
          setError(t('aiProviderDialog.newRequiresKeyAndModel'))
          return
        }
        await create.mutateAsync({
          body: {
            name: name.trim(),
            provider_type: vendor,
            model_name: model.trim(),
            api_key: key.trim(),
          },
        })
      } else {
        const patch: ProviderPatch = {}
        if (name !== provider.name) patch.name = name.trim()
        if (vendor !== provider.provider_type) patch.provider_type = vendor
        if (model !== (provider.model_name ?? ''))
          patch.model_name = model.trim() === '' ? null : model.trim()
        if (key !== undefined) patch.api_key = key === null ? null : key.trim()
        await update.mutateAsync({ path: { provider_id: provider.id }, body: patch })
      }
      await queryClient.invalidateQueries({ queryKey: aiProvidersListQueryKey() })
      toast.success(t('aiProviderDialog.saved'))
      onClose()
    } catch (cause) {
      setError(apiErrorMessage(cause, t('aiProviderDialog.saveFailed')))
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) close()
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>
            {provider === null ? t('aiProviderDialog.addTitle') : t('aiProviderDialog.editTitle')}
          </DialogTitle>
          <DialogDescription>{t('aiProviderDialog.description')}</DialogDescription>
        </DialogHeader>
        <form
          onSubmit={(event) => void save(event)}
          className="space-y-4"
          data-automation-id="AIProvider-form"
        >
          <label className="flex flex-col gap-1 text-sm font-medium">
            {t('aiProviderDialog.name')}
            <input
              className={INPUT_CLASS}
              required
              maxLength={100}
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium">
            {t('aiProviderDialog.vendor')}
            <select
              className={INPUT_CLASS}
              value={vendor}
              onChange={(event) => setVendor(zAiProviderTypes.parse(event.target.value))}
            >
              {zAiProviderTypes.options.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-sm font-medium">
            {t('aiProviderDialog.model')}
            <input
              className={INPUT_CLASS}
              required={provider === null}
              maxLength={100}
              value={model}
              onChange={(event) => setModel(event.target.value)}
            />
          </label>
          <SecretField
            section="ai"
            fieldKey="api_key"
            label={t('aiProviderDialog.apiKey')}
            configured={provider?.has_api_key ?? false}
            draft={key}
            onChange={setKey}
          />
          {error && (
            <p role="alert" className="text-sm text-red-700">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" disabled={saving} onClick={close}>
              {t('aiProviderDialog.cancel')}
            </Button>
            <Button type="submit" disabled={saving || !dirty}>
              {saving ? t('aiProviderDialog.saving') : t('aiProviderDialog.save')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
