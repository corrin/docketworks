import { toast } from 'vue-sonner'
import { debugLog } from '@/utils/debug'

export function useJobNotifications() {
  const notifyJobUpdated = (jobName: string) => {
    toast.success('Job updated successfully', {
      description: `${jobName} was successfully updated`,
    })
  }

  const notifyJobLoaded = (jobName: string) => {
    debugLog(`Job ${jobName} loaded successfully`)
  }

  const notifyJobError = (jobId: string, error: string) => {
    toast.error('Error updating job', {
      description: `Error loading job ${jobId}: ${error}`,
    })
  }

  const notifyFileUploaded = (fileName: string) => {
    toast.success('File uploaded', {
      description: `${fileName} was successfully uploaded`,
    })
  }

  const notifyFileDeleted = (fileName: string) => {
    toast.success('File deleted', {
      description: `${fileName} was successfully deleted`,
    })
  }

  const notifyQuoteCreated = () => {
    toast.success('Quote created', {
      description: 'Quote was created and sent successfully',
    })
  }

  const notifyQuoteAccepted = () => {
    toast.success('Quote accepted', {
      description: 'Quote was accepted by the client',
    })
  }

  const notifyInvoiceCreated = () => {
    toast.success('Invoice created', {
      description: 'Invoice was created and sent successfully',
    })
  }

  const notifyDataChanged = (dataType: string) => {
    // Reduced verbosity - only debug log for auto-save
    debugLog(`${dataType} changed - auto-saving`)
  }

  const notifyEventAdded = (eventType: string) => {
    toast.success('Event added', {
      description: `Event "${eventType}" was successfully added`,
    })
  }

  const notifyPricingUpdated = () => {
    // Reduced verbosity - only debug log for pricing updates
    debugLog('Pricing data updated automatically')
  }

  const notifyQuoteLinkStart = () => {
    toast.info('Linking spreadsheet...', {
      description: 'Creating and configuring quote spreadsheet',
      id: 'quote-link',
    })
  }

  const notifyQuoteLinkSuccess = (sheetUrl?: string) => {
    toast.success('Spreadsheet linked successfully!', {
      description: sheetUrl
        ? 'The spreadsheet has been created and can now be accessed'
        : 'Quote spreadsheet has been linked',
      id: 'quote-link',
      action: sheetUrl
        ? {
            label: 'Open Spreadsheet',
            onClick: () => window.open(sheetUrl, '_blank'),
          }
        : undefined,
    })
  }

  const notifyQuoteLinkError = (error: string) => {
    toast.error('Error linking spreadsheet', {
      description: error,
      id: 'quote-link',
    })
  }

  const notifyQuoteRefreshStart = () => {
    toast.info('Fetching updates...', {
      description: 'Checking for changes in the spreadsheet',
      id: 'quote-refresh',
    })
  }

  const notifyQuoteRefreshSuccess = (changesCount: number = 0) => {
    if (changesCount > 0) {
      toast.success('Quote updated!', {
        description: `${changesCount} changes were applied`,
        id: 'quote-refresh',
      })
    } else {
      toast.info('No changes found', {
        description: 'The spreadsheet is synchronized with the system',
        id: 'quote-refresh',
        duration: 4000,
      })
    }
  }

  const notifyQuoteRefreshError = (error: string) => {
    toast.error('Error updating quote', {
      description: error,
      id: 'quote-refresh',
    })
  }

  const notifySaveStart = (dataType: string = 'data') => {
    toast.info(`Saving ${dataType}...`, {
      id: 'save-data',
    })
  }

  const notifySaveSuccess = (dataType: string = 'data') => {
    toast.success(`${dataType} saved!`, {
      description: 'All changes have been saved',
      id: 'save-data',
    })
  }

  const notifySaveError = (error: string, dataType: string = 'data') => {
    toast.error(`Error saving ${dataType}`, {
      description: error,
      id: 'save-data',
    })
  }

  const notifyDeleteStart = (itemType: string) => {
    toast.info(`Deleting ${itemType}...`, {
      id: 'delete-item',
    })
  }

  const notifyDeleteSuccess = (itemType: string) => {
    toast.success(`${itemType} deleted!`, {
      description: `${itemType} was permanently removed`,
      id: 'delete-item',
    })
  }

  const notifyDeleteError = (error: string, itemType: string) => {
    toast.error(`Error deleting ${itemType}`, {
      description: error,
      id: 'delete-item',
    })
  }

  const notifyApiError = (operation: string, error: string) => {
    toast.error(`Error in operation: ${operation}`, {
      description: error,
    })
  }

  const notifyApiSuccess = (operation: string, description?: string) => {
    toast.success(`${operation} completed!`, {
      description: description || 'Operation completed successfully',
    })
  }

  const showLoadingToast = (message: string, description?: string, id?: string) => {
    return toast.info(message, {
      description,
      id: id || 'loading',
    })
  }

  const dismissToast = (id: string) => {
    toast.dismiss(id)
  }

  return {
    notifyJobUpdated,
    notifyJobLoaded,
    notifyJobError,
    notifyFileUploaded,
    notifyFileDeleted,
    notifyQuoteCreated,
    notifyQuoteAccepted,
    notifyInvoiceCreated,
    notifyDataChanged,
    notifyEventAdded,
    notifyPricingUpdated,

    notifyQuoteLinkStart,
    notifyQuoteLinkSuccess,
    notifyQuoteLinkError,
    notifyQuoteRefreshStart,
    notifyQuoteRefreshSuccess,
    notifyQuoteRefreshError,

    notifySaveStart,
    notifySaveSuccess,
    notifySaveError,

    notifyDeleteStart,
    notifyDeleteSuccess,
    notifyDeleteError,

    notifyApiError,
    notifyApiSuccess,

    showLoadingToast,
    dismissToast,
  }
}
