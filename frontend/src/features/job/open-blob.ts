import { toast } from 'sonner'

import { apiErrorMessage } from '@/api'
import { i18n } from '@/lib/i18n'
import { revokeObjectUrlLater, saveObjectUrl } from '@/lib/download'

interface OpenBlobOptions {
  /** Auto-print once the tab loads (the print buttons); downloads skip it. */
  print: boolean
  /** Also save the file via an anchor download, v1's download behaviour. */
  downloadName?: string
}

/**
 * Fetch a blob and open it in a new tab. A blocked popup is the user's
 * browser talking, not a defect — it toasts; a console.error here would
 * fail every E2E spec.
 */
export async function openBlobInNewTab(
  fetchBlob: () => Promise<unknown>,
  label: string,
  options: OpenBlobOptions,
): Promise<void> {
  let data: unknown
  try {
    data = await fetchBlob()
  } catch (error) {
    toast.error(apiErrorMessage(error, i18n.t('job:openBlob.fetchFailed', { label })))
    return
  }
  if (!(data instanceof Blob)) {
    toast.error(i18n.t('job:openBlob.notADocument', { label }))
    return
  }

  const url = URL.createObjectURL(data)

  if (options.downloadName !== undefined) {
    saveObjectUrl(url, options.downloadName)
  }

  const win = window.open(url, '_blank')
  // Revoked on every path: a tab closed before its load event would
  // otherwise leak the object URL for the session's lifetime. lib/download
  // owns how long the delay is.
  revokeObjectUrlLater(url)
  if (!win) {
    if (options.downloadName === undefined) {
      toast.error(i18n.t('job:openBlob.printBlocked'))
    } else {
      toast.error(i18n.t('job:openBlob.attachmentBlocked'))
    }
    return
  }
  win.addEventListener('load', () => {
    if (options.print) {
      win.print()
    }
  })
}
