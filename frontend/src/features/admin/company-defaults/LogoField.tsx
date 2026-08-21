import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  companyDefaultsLogoDestroyMutation,
  companyDefaultsLogoUpdateMutation,
  companyDefaultsRetrieveQueryKey,
} from '@/api'
import { Button } from '@/components/ui/button'

import { aspectRatioProblem } from './logoAspectRatio'
import type { SettingsFieldInputProps } from './SettingsFieldInput'

// The server validates png/jpg/jpeg/gif/webp only (no svg) and PIL-verifies
// the upload; the accept list mirrors that so the file picker never offers a
// format the server will refuse.
const LOGO_ACCEPT = 'image/png,image/jpeg,image/gif,image/webp'

/** The logo endpoints' path param is a closed union; a plain cast from
 * field.key (string) would be unsafe (ADR 0028), so this is fail-early
 * instead — a settings-schema entry of type "image" with any other key is a
 * registry defect, not a value to coerce (ADR 0015). */
function requireLogoFieldName(key: string): 'logo' | 'logo_wide' {
  if (key === 'logo' || key === 'logo_wide') return key
  throw new Error(`LogoField does not support the "${key}" field.`)
}

/**
 * Preview + upload + remove for a logo slot, using the generated multipart
 * mutations directly (v1's Zodios-can't-multipart workaround is dead). `value`
 * is the live `${field.key}_url` from the shell-owned company-defaults query,
 * not the mounted snapshot, so a fresh upload/delete shows immediately.
 */
export function LogoField({ field, value, section }: SettingsFieldInputProps) {
  const queryClient = useQueryClient()
  const uploadMutation = useMutation(companyDefaultsLogoUpdateMutation())
  const destroyMutation = useMutation(companyDefaultsLogoDestroyMutation())
  const [validationError, setValidationError] = useState<string | null>(null)
  const automationId = `CompanyDefaultsPage-${section}-field-${field.key}`
  const url = typeof value === 'string' ? value : null
  const fieldName = requireLogoFieldName(field.key)

  async function onFile(file: File) {
    const problem = await aspectRatioProblem(field.key, file)
    if (problem) {
      setValidationError(problem)
      return
    }
    setValidationError(null)
    try {
      const fresh = await uploadMutation.mutateAsync({
        path: { field_name: fieldName },
        body: { file },
      })
      queryClient.setQueryData(companyDefaultsRetrieveQueryKey(), fresh)
      toast.success('Logo uploaded')
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Failed to upload logo'))
    }
  }

  async function onRemove() {
    try {
      const fresh = await destroyMutation.mutateAsync({ path: { field_name: fieldName } })
      queryClient.setQueryData(companyDefaultsRetrieveQueryKey(), fresh)
      toast.success('Logo removed')
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Failed to remove logo'))
    }
  }

  return (
    <div className="flex flex-col gap-2">
      {url ? (
        <img
          src={url}
          alt={field.label}
          className="h-16 w-auto max-w-full rounded border border-slate-200 object-contain"
        />
      ) : (
        <p className="text-xs text-slate-500">No image</p>
      )}
      <div className="flex items-center gap-2">
        {/* A visible <label> wrapping a hidden file input keeps the control
         * keyboard-reachable and screen-reader-named without a synthetic
         * click() call from a ref. */}
        <label className="inline-flex cursor-pointer items-center rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50">
          Upload
          <input
            type="file"
            accept={LOGO_ACCEPT}
            className="sr-only"
            aria-label={`Upload ${field.label}`}
            data-automation-id={`${automationId}-upload`}
            onChange={(event) => {
              const file = event.target.files?.[0]
              event.target.value = ''
              if (file) void onFile(file)
            }}
          />
        </label>
        {url && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => void onRemove()}
            data-automation-id={`${automationId}-remove`}
          >
            Remove
          </Button>
        )}
      </div>
      {validationError && <p className="text-xs text-red-700">{validationError}</p>}
    </div>
  )
}
