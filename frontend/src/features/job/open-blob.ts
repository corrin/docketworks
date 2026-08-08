import { toast } from 'sonner'

import { apiErrorMessage } from '@/api'

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
    toast.error(apiErrorMessage(error, `Failed to fetch the ${label}.`))
    return
  }
  if (!(data instanceof Blob)) {
    toast.error(`The ${label} response was not a document.`)
    return
  }

  const url = URL.createObjectURL(data)
  const revokeLater = () => setTimeout(() => URL.revokeObjectURL(url), 60_000)

  if (options.downloadName !== undefined) {
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = options.downloadName
    anchor.click()
  }

  const win = window.open(url, '_blank')
  if (!win) {
    if (options.downloadName === undefined) {
      toast.error('Failed to open print window — check the popup blocker.')
    } else {
      toast.error('Failed to open the attachment — check the popup blocker.')
    }
    revokeLater()
    return
  }
  win.addEventListener('load', () => {
    if (options.print) {
      win.print()
    }
    // The document is fetched once load fires; the object URL only leaks
    // memory after that. The delay covers slow same-tab reload edge cases.
    revokeLater()
  })
}
