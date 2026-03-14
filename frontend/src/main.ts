import './assets/main.css'
import '@fontsource-variable/inter'

import { createApp } from 'vue'
import { createPinia } from 'pinia'

import App from './App.vue'
import router from './router'

import './plugins/axios'
import './plugins/ag-grid'

import './polyfills'
import { NativeEventSource, EventSourcePolyfill } from 'event-source-polyfill'

const Impl = NativeEventSource || EventSourcePolyfill

declare global {
  interface Window {
    EventSource: typeof EventSource
  }
}
window.EventSource = Impl as unknown as typeof EventSource

const app = createApp(App)

const pinia = createPinia()
app.use(pinia)
app.use(router)

// Set up ETag manager after Pinia is initialized
import {
  setupETagManager,
  setupJobReloadManager,
  setupPoETagManager,
  setupPoReloadManager,
} from './api/client'
import { useJobETags } from './composables/useJobETags'
import { usePoETags } from './composables/usePoETags'
import { useJobsStore } from './stores/jobs'
import { usePurchaseOrderStore } from './stores/purchaseOrderStore'

// Initialize the ETag manager with the composable
const { getETag: getJobETag, setETag: setJobETag } = useJobETags()
setupETagManager({ getETag: getJobETag, setETag: setJobETag })

// Initialize the job reload manager with the store
const jobsStore = useJobsStore(pinia)
setupJobReloadManager({
  reloadJobOnConflict: (jobId: string) => jobsStore.reloadJobOnConflict(jobId),
})

// Initialize the PO ETag manager with the composable
const { getETag: getPoETag, setETag: setPoETag } = usePoETags()
setupPoETagManager({ getETag: getPoETag, setETag: setPoETag })

// Initialize the PO reload manager with the store
const poStore = usePurchaseOrderStore(pinia)
setupPoReloadManager({
  reloadPoOnConflict: (poId: string) => poStore.reloadPoOnConflict(poId),
})

// Note: Delivery receipts use the same PO reload manager as purchase orders

app.mount('#app')
