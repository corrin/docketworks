<template>
  <div v-if="isStaff" class="admin-layout">
    <!-- Sidebar -->
    <nav class="sidebar">
      <div class="user-card">
        <div class="avatar">
          <svg class="w-10 h-10 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <circle cx="12" cy="12" r="10" stroke-width="2" />
            <path d="M12 6v6l4 2" stroke-width="2" />
          </svg>
        </div>
        <div class="user-name">Welcome, {{ username }}!</div>
        <div class="user-date">{{ today }}</div>
      </div>
      <ul class="tab-list">
        <li v-for="tab in tabs" :key="tab.key">
          <RouterLink
            :to="{ name: tab.route }"
            class="tab-link"
            :class="isActive(tab.key) ? 'tab-link--active' : ''"
          >
            <span v-if="tab.icon" class="tab-icon">
              <component :is="tab.icon" />
            </span>
            {{ tab.label }}
          </RouterLink>
        </li>
      </ul>
      <div class="sidebar-footer text-white bold">Admin Panel</div>
    </nav>
    <!-- Main Content -->
    <main class="admin-main">
      <RouterView />
    </main>
  </div>
  <div v-else class="text-center text-red-500 py-10">
    You do not have permission to access the admin panel.
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useAppLayout } from '@/composables/useAppLayout'
import { adminPages } from '@/config/adminPages'
import { debugLog } from '../utils/debug'

const { userInfo } = useAppLayout()
const isStaff = computed(() => Boolean(userInfo.value?.is_office_staff))
const route = useRoute()

const username = computed(() => {
  return (
    userInfo.value.displayName.trim() ||
    userInfo.value.fullName.trim() ||
    userInfo.value.first_name.trim()
  )
})

debugLog('UserInfo in AdminView:', userInfo.value)

const today = new Date().toLocaleDateString('en-NZ', {
  weekday: 'long',
  year: 'numeric',
  month: 'long',
  day: 'numeric',
})

// Use centralized admin pages config
const tabs = computed(() =>
  adminPages.map((page) => ({
    key: page.key,
    label: page.label,
    route: page.name,
    icon: page.icon,
  })),
)

function isActive(key: string) {
  return route.name === `admin-${key}`
}
</script>

<style scoped>
.admin-layout {
  display: flex;
  max-height: 100vh;
  height: auto;
  background: #f4f4f5;
  overflow: hidden;
}

.sidebar {
  width: 18rem;
  min-width: 15rem;
  background: linear-gradient(to bottom, #e0e7ff, #c7d2fe 60%, #a5b4fc 100%);
  color: #3730a3;
  display: flex;
  flex-direction: column;
  padding: 2rem 1.5rem 1.5rem 1.5rem;
  gap: 2rem;
  box-shadow: 0 8px 32px 0 rgba(49, 46, 129, 0.12);
  border-top-right-radius: 1.5rem;
  border-bottom-right-radius: 1.5rem;
  align-self: stretch;
  height: 100vh;
  margin-top: 8vh;
}

.user-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 1.5rem;
}

.avatar {
  width: 4rem;
  height: 4rem;
  border-radius: 9999px;
  background: #6366f1;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 4px 16px 0 rgba(99, 102, 241, 0.18);
  margin-bottom: 0.5rem;
  animation: bounce 1.2s infinite alternate;
}

@keyframes bounce {
  0% {
    transform: translateY(0);
  }

  100% {
    transform: translateY(-8px);
  }
}

.user-name {
  font-size: 1.125rem;
  font-weight: bold;
  margin-top: 0.25rem;
  color: #3730a3;
}

.user-date {
  font-size: 0.95rem;
  color: #6366f1;
}

.user-quote {
  font-style: italic;
  color: #818cf8;
  font-size: 0.8rem;
  margin-top: 0.25rem;
  animation: pulse 2s infinite alternate;
}

@keyframes pulse {
  0% {
    opacity: 0.7;
  }

  100% {
    opacity: 1;
  }
}

.tab-list {
  flex: 1 1 0;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-bottom: 1rem;
}

.tab-link {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-radius: 0.75rem;
  font-weight: 600;
  font-size: 1rem;
  color: #3730a3;
  background: transparent;
  transition: all 0.15s;
  box-shadow: none;
}

.tab-link--active {
  background: #6366f1;
  color: #fff;
  box-shadow: 0 2px 8px 0 rgba(99, 102, 241, 0.12);
  transform: scale(1.04);
}

.tab-link:not(.tab-link--active):hover {
  background: #a5b4fc;
  color: #3730a3;
}

.tab-icon {
  width: 1.25rem;
  height: 1.25rem;
  display: flex;
  align-items: center;
  justify-content: center;
}

.sidebar-footer {
  margin-top: auto;
  font-size: 1.1rem;
  text-align: center;
  opacity: 1;
  padding-bottom: 0.5rem;
  margin-bottom: 4rem;
  font-weight: bold;
  color: #3730a3;
  text-decoration: underline overline;
  text-underline-offset: 6px;
  text-decoration-thickness: 3px;
  letter-spacing: 1px;
}

.admin-main {
  flex: 1 1 0;
  min-height: 0;
  height: auto;
  overflow-y: auto;
  background: #f4f4f5;
  padding: 0;
  min-width: 0;
}
</style>
