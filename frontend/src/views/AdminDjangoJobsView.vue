<template>
  <AppLayout>
    <div class="w-full h-full flex flex-col overflow-hidden">
      <div class="max-w-screen-xl mx-auto py-6 px-2 md:px-8 h-full flex flex-col gap-6">
        <div class="flex items-center justify-between mb-2">
          <h1 class="text-2xl font-bold text-indigo-700 flex items-center gap-2">
            <CalendarClock class="w-7 h-7 text-indigo-400 animate-pulse" />
            Django Jobs
          </h1>
        </div>
        <div class="flex flex-col items-center justify-center" style="height: 60vh">
          <div class="grid grid-cols-2 gap-8 w-full max-w-2xl">
            <button class="section-btn" @click="openJobsModal">
              <CalendarClock class="w-12 h-12 mb-2" />
              <span>Django Jobs</span>
            </button>
            <button class="section-btn" @click="openExecutionsModal">
              <ListChecks class="w-12 h-12 mb-2" />
              <span>Job Executions</span>
            </button>
          </div>
        </div>
        <JobsModal v-if="showJobsModal" @close="closeJobsModal" class="w-[90vw]" />
        <ExecutionsModal v-if="showExecutionsModal" @close="closeExecutionsModal" />
      </div>
    </div>
  </AppLayout>
</template>

<script setup lang="ts">
import AppLayout from '@/components/AppLayout.vue'
import { CalendarClock, ListChecks } from 'lucide-vue-next'
import { ref } from 'vue'
import JobsModal from '@/components/JobsModal.vue'
import ExecutionsModal from '@/components/ExecutionsModal.vue'

const showJobsModal = ref(false)
const showExecutionsModal = ref(false)

function openJobsModal() {
  showJobsModal.value = true
}
function closeJobsModal() {
  showJobsModal.value = false
}
function openExecutionsModal() {
  showExecutionsModal.value = true
}
function closeExecutionsModal() {
  showExecutionsModal.value = false
}
</script>

<style scoped>
.section-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.8);
  border-radius: 0.75rem;
  box-shadow: 0 2px 12px 0 rgba(80, 80, 120, 0.08);
  padding: 1.5rem;
  color: #3730a3;
  font-weight: 600;
  font-size: 1.125rem;
  transition:
    background 0.2s,
    transform 0.2s;
  min-width: 180px;
  min-height: 140px;
  border: none;
  outline: none;
  cursor: pointer;
}
.section-btn:hover,
.section-btn:focus {
  background: linear-gradient(135deg, #c7d2fe 0%, #e0e7ff 100%);
  transform: scale(1.05);
  box-shadow: 0 4px 24px 0 rgba(80, 80, 120, 0.13);
}
</style>
