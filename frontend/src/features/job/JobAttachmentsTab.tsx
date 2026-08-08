import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  deleteJobFile,
  getJobFile,
  listJobFilesOptions,
  uploadJobFiles,
} from '@/api'
import { openBlobInNewTab } from './open-blob'

interface PendingUpload {
  key: string
  filename: string
  status: 'uploading' | 'saving'
}

/**
 * Job attachments: upload via the always-mounted hidden file input (the E2E
 * contract drives it with setInputFiles, so it must never unmount), an
 * optimistic pending row that is replaced in place by the server row, and
 * delete behind the NATIVE window.confirm — the specs arm a dialog handler,
 * which a custom modal would leave dangling.
 */
export function JobAttachmentsTab({ jobId }: { jobId: string }) {
  const queryClient = useQueryClient()
  const filesQuery = useQuery(listJobFilesOptions({ path: { job_id: jobId } }))
  const [pendingUploads, setPendingUploads] = useState<PendingUpload[]>([])
  const [removedIds, setRemovedIds] = useState<ReadonlySet<string>>(new Set())

  const files = (filesQuery.data ?? []).filter((file) => !removedIds.has(file.id))

  const handleUpload = async (fileList: FileList) => {
    const selected = Array.from(fileList)
    const [firstFile] = selected
    if (firstFile === undefined) {
      return
    }
    // One POST carries the whole selection; each file gets its own pending
    // row so a multi-file upload doesn't masquerade as one file.
    const batch: PendingUpload[] = selected.map((file) => ({
      key: crypto.randomUUID(),
      filename: file.name,
      status: 'uploading',
    }))
    const batchKeys = new Set(batch.map((upload) => upload.key))
    const setStatus = (status: PendingUpload['status']) => {
      setPendingUploads((current) =>
        current.map((upload) => (batchKeys.has(upload.key) ? { ...upload, status } : upload)),
      )
    }
    setPendingUploads((current) => [...batch, ...current])

    try {
      await uploadJobFiles({
        path: { job_id: jobId },
        body: { files: selected },
        throwOnError: true,
        onUploadProgress: (progress) => {
          // The bytes are all sent at 100%; the server is still writing them,
          // which is a different wait the row should name.
          if (progress.total !== undefined && progress.loaded >= progress.total) {
            setStatus('saving')
          }
        },
      })
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Failed to upload the attachment.'))
      setPendingUploads((current) => current.filter((upload) => !batchKeys.has(upload.key)))
      return
    }

    await queryClient.invalidateQueries({
      queryKey: listJobFilesOptions({ path: { job_id: jobId } }).queryKey,
    })
    setPendingUploads((current) => current.filter((upload) => !batchKeys.has(upload.key)))
  }

  const handleDownload = async (fileId: string, filename: string) => {
    // print: true is v1's download behaviour — it opens the file for
    // viewing/printing AND saves it; the download alone would be a silent
    // functional change.
    await openBlobInNewTab(
      async () =>
        (
          await getJobFile({
            path: { job_id: jobId, file_id: fileId },
            responseType: 'blob',
            throwOnError: true,
          })
        ).data,
      'attachment',
      { print: true, downloadName: filename },
    )
  }

  const handleDelete = async (fileId: string, filename: string) => {
    // Native confirm, not a modal: the E2E contract answers a browser dialog.
    if (!window.confirm(`Delete ${filename}?`)) {
      return
    }
    try {
      await deleteJobFile({ path: { job_id: jobId, file_id: fileId }, throwOnError: true })
    } catch (error) {
      toast.error(apiErrorMessage(error, 'Failed to delete the attachment.'))
      return
    }
    setRemovedIds((current) => new Set([...current, fileId]))
    await queryClient.invalidateQueries({
      queryKey: listJobFilesOptions({ path: { job_id: jobId } }).queryKey,
    })
  }

  return (
    <div className="max-w-3xl p-6">
      <h2 className="mb-4 text-lg font-semibold text-gray-900">Job Attachments</h2>

      <label className="inline-flex cursor-pointer items-center rounded-md border border-gray-300 px-3 py-2 text-sm transition-colors hover:bg-gray-50">
        <Upload className="mr-2 h-4 w-4" />
        Upload files
        <input
          type="file"
          multiple
          className="hidden"
          data-automation-id="JobAttachmentsTab-file-input"
          onChange={(event) => {
            const fileList = event.target.files
            if (fileList) {
              void handleUpload(fileList)
            }
            event.target.value = ''
          }}
        />
      </label>

      <div className="mt-4 space-y-2">
        {pendingUploads.map((upload) => (
          <div
            key={upload.key}
            className="flex items-center justify-between rounded-md border border-blue-200 bg-blue-50 px-3 py-2"
          >
            <span className="text-sm font-medium text-gray-900">{upload.filename}</span>
            <span className="text-xs text-blue-700">
              {upload.status === 'uploading' ? 'Uploading...' : 'Saving...'}
            </span>
          </div>
        ))}

        {files.map((file) => (
          <div
            key={file.id}
            data-automation-id={`JobAttachmentsTab-file-row-${file.id}`}
            className="flex items-center justify-between rounded-md border border-gray-200 px-3 py-2"
          >
            <span className="text-sm font-medium text-gray-900">{file.filename}</span>
            <div className="flex items-center space-x-1">
              <button
                type="button"
                data-automation-id={`JobAttachmentsTab-download-${file.id}`}
                className="p-1.5 text-gray-500 transition-colors hover:text-blue-600"
                title={`Download ${file.filename}`}
                onClick={() => {
                  void handleDownload(file.id, file.filename)
                }}
              >
                <Download className="h-4 w-4" />
              </button>
              <button
                type="button"
                data-automation-id={`JobAttachmentsTab-delete-${file.id}`}
                className="p-1.5 text-gray-500 transition-colors hover:text-red-600"
                title={`Delete ${file.filename}`}
                onClick={() => {
                  void handleDelete(file.id, file.filename)
                }}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </div>
        ))}

        {filesQuery.isError && (
          <div className="text-sm text-red-600">
            Failed to load attachments.
            <button
              type="button"
              className="ml-2 underline"
              onClick={() => {
                void filesQuery.refetch()
              }}
            >
              Retry
            </button>
          </div>
        )}

        {pendingUploads.length === 0 && files.length === 0 && filesQuery.isSuccess && (
          <p className="text-sm text-gray-500">No attachments yet.</p>
        )}
      </div>
    </div>
  )
}
