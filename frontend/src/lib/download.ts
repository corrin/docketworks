/**
 * The one owner of "hand this to the browser as a file". Every save path —
 * a generated CSV, a fetched PDF — goes through here so there is one answer
 * to when the object URL is released.
 */

// Opus: 60 seconds rather than revoking on the next statement. `click()`
// dispatches synchronously but the download it starts is queued, so an
// immediate revoke races the browser reading the blob; Chromium happens to
// win that race, which is why a chromium-only E2E run cannot catch it.
const REVOKE_AFTER_MS = 60_000

/** Release an object URL once any download or tab that wants it has read it. */
export function revokeObjectUrlLater(url: string): void {
  setTimeout(() => {
    URL.revokeObjectURL(url)
  }, REVOKE_AFTER_MS)
}

/**
 * Save an existing object URL under a filename. Separate from `saveBlob` for
 * the caller that also opens the same URL in a tab — minting a second URL
 * for one blob would double what has to be revoked.
 *
 * The anchor is attached before clicking: not every browser dispatches a
 * click on a detached anchor, and the node is removed again so an
 * export-per-click page accumulates nothing.
 */
export function saveObjectUrl(url: string, filename: string): void {
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
}

/** Save a blob under a filename, releasing its URL afterwards. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  saveObjectUrl(url, filename)
  revokeObjectUrlLater(url)
}
