<template>
  <div
    class="min-h-screen flex items-center justify-center bg-gradient-to-br from-blue-50 via-indigo-50 to-purple-50 py-12 px-4 sm:px-6 lg:px-8 relative overflow-hidden"
  >
    <!-- Background animation elements -->
    <div class="absolute inset-0 overflow-hidden">
      <div
        class="absolute -top-40 -right-32 w-80 h-80 bg-gradient-to-br from-blue-400/20 to-indigo-600/20 rounded-full blur-3xl animate-float"
      ></div>
      <div
        class="absolute -bottom-40 -left-32 w-80 h-80 bg-gradient-to-br from-purple-400/20 to-pink-600/20 rounded-full blur-3xl animate-float-delayed"
      ></div>
      <div
        class="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-gradient-to-br from-indigo-400/10 to-blue-600/10 rounded-full blur-3xl animate-pulse-slow"
      ></div>
    </div>

    <div class="max-w-md w-full space-y-8 relative z-10">
      <!-- Logo and header section -->
      <div class="text-center animate-fade-in-up">
        <div class="flex justify-center mb-8">
          <div class="relative">
            <img src="/logo.png" alt="Company Logo" class="h-32 w-auto animate-logo-entrance" />
            <div
              class="absolute inset-0 bg-gradient-to-r from-blue-500/20 to-indigo-500/20 rounded-lg blur-xl animate-glow"
            ></div>
          </div>
        </div>
        <h1
          class="text-4xl font-bold bg-gradient-to-r from-blue-600 to-indigo-600 bg-clip-text text-transparent animate-fade-in-up animation-delay-300"
        >
          Jobs Manager
        </h1>
        <p class="mt-3 text-gray-600 animate-fade-in-up animation-delay-500">
          Welcome back! Sign in to your account
        </p>
      </div>

      <!-- Login form -->
      <div
        class="bg-white/80 backdrop-blur-lg rounded-2xl shadow-xl border border-white/20 p-8 animate-slide-up animation-delay-700"
      >
        <form @submit.prevent="handleLogin" class="space-y-6">
          <div class="animate-fade-in-up animation-delay-900">
            <label for="username" class="block text-sm font-semibold text-gray-700 mb-2">
              E-mail
            </label>
            <div class="relative">
              <input
                id="username"
                v-model="credentials.username"
                type="text"
                class="w-full px-4 py-3 bg-white/50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200 placeholder-gray-400"
                :class="{
                  'border-red-400 focus:ring-red-500': hasError && !credentials.username,
                  'border-gray-200 focus:ring-blue-500': !(hasError && !credentials.username),
                }"
                placeholder="Enter your username"
                required
                autocomplete="username"
              />
              <div
                class="absolute inset-0 rounded-xl bg-gradient-to-r from-blue-500/5 to-indigo-500/5 pointer-events-none"
              ></div>
            </div>
          </div>

          <div class="animate-fade-in-up animation-delay-1000">
            <label for="password" class="block text-sm font-semibold text-gray-700 mb-2">
              Password
            </label>
            <div class="relative">
              <input
                id="password"
                v-model="credentials.password"
                :type="showPassword ? 'text' : 'password'"
                class="w-full px-4 py-3 pr-12 bg-white/50 border border-gray-200 rounded-xl focus:ring-2 focus:ring-blue-500 focus:border-transparent transition-all duration-200 placeholder-gray-400"
                :class="{
                  'border-red-400 focus:ring-red-500': hasError && !credentials.password,
                  'border-gray-200 focus:ring-blue-500': !(hasError && !credentials.password),
                }"
                placeholder="Enter your password"
                required
                autocomplete="current-password"
              />
              <button
                type="button"
                class="absolute inset-y-0 right-0 flex items-center pr-3 text-gray-400 hover:text-gray-600 transition-colors duration-200"
                @click="togglePasswordVisibility"
              >
                <Eye v-if="!showPassword" class="h-5 w-5" />
                <EyeOff v-else class="h-5 w-5" />
              </button>
              <div
                class="absolute inset-0 rounded-xl bg-gradient-to-r from-blue-500/5 to-indigo-500/5 pointer-events-none"
              ></div>
            </div>
          </div>

          <div
            v-if="error"
            class="bg-red-50/80 backdrop-blur-sm border border-red-200 text-red-700 px-4 py-3 rounded-xl text-sm animate-shake"
          >
            {{ error }}
          </div>

          <button
            type="submit"
            class="w-full bg-gradient-to-r from-blue-500 to-indigo-600 hover:from-blue-600 hover:to-indigo-700 text-white font-semibold py-3 px-6 rounded-xl transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed transform hover:scale-105 active:scale-95 shadow-lg hover:shadow-xl animate-fade-in-up animation-delay-1100"
            :disabled="isLoading || !isFormValid"
          >
            <span v-if="isLoading" class="flex items-center justify-center">
              <svg
                class="animate-spin -ml-1 mr-3 h-5 w-5 text-white"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
              >
                <circle
                  class="opacity-25"
                  cx="12"
                  cy="12"
                  r="10"
                  stroke="currentColor"
                  stroke-width="4"
                ></circle>
                <path
                  class="opacity-75"
                  fill="currentColor"
                  d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
                ></path>
              </svg>
              Signing in...
            </span>
            <span v-else>Sign In</span>
          </button>
        </form>

        <!-- Footer -->
        <div class="mt-8 text-center animate-fade-in-up animation-delay-1200">
          <p class="text-xs text-gray-500">Jobs Manager System</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Eye, EyeOff } from 'lucide-vue-next'
import { useLogin } from '@/composables/useLogin'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const { credentials, hasError, isFormValid, isLoading, error, handleLogin } = useLogin()

const authStore = useAuthStore()
const router = useRouter()

const showPassword = ref(false)

const togglePasswordVisibility = () => {
  showPassword.value = !showPassword.value
}

onMounted(async () => {
  if (!authStore.user && !authStore.hasCheckedSession) {
    await authStore.initializeAuth()
  }

  if (authStore.isAuthenticated) {
    await router.push({ name: authStore.defaultRouteName })
  }
})
</script>

<style scoped>
/* Custom animations */
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes slideUp {
  from {
    opacity: 0;
    transform: translateY(50px);
  }

  to {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes logoEntrance {
  0% {
    opacity: 0;
    transform: scale(0.5) rotate(-180deg);
  }

  50% {
    opacity: 0.8;
    transform: scale(1.1) rotate(-90deg);
  }

  100% {
    opacity: 1;
    transform: scale(1) rotate(0deg);
  }
}

@keyframes float {
  0%,
  100% {
    transform: translateY(0px);
  }

  50% {
    transform: translateY(-20px);
  }
}

@keyframes floatDelayed {
  0%,
  100% {
    transform: translateY(0px);
  }

  50% {
    transform: translateY(-15px);
  }
}

@keyframes glow {
  0%,
  100% {
    opacity: 0.5;
  }

  50% {
    opacity: 0.8;
  }
}

@keyframes shake {
  0%,
  100% {
    transform: translateX(0);
  }

  10%,
  30%,
  50%,
  70%,
  90% {
    transform: translateX(-5px);
  }

  20%,
  40%,
  60%,
  80% {
    transform: translateX(5px);
  }
}

@keyframes pulseSlowly {
  0%,
  100% {
    opacity: 0.3;
  }

  50% {
    opacity: 0.6;
  }
}

/* Animation classes */
.animate-fade-in-up {
  animation: fadeInUp 0.8s ease-out;
}

.animate-slide-up {
  animation: slideUp 0.8s ease-out;
}

.animate-logo-entrance {
  animation: logoEntrance 1.2s ease-out;
}

.animate-float {
  animation: float 6s ease-in-out infinite;
}

.animate-float-delayed {
  animation: floatDelayed 8s ease-in-out infinite 2s;
}

.animate-glow {
  animation: glow 3s ease-in-out infinite;
}

.animate-shake {
  animation: shake 0.5s ease-in-out;
}

.animate-pulse-slow {
  animation: pulseSlowly 4s ease-in-out infinite;
}

/* Animation delays */
.animation-delay-300 {
  animation-delay: 0.3s;
  animation-fill-mode: both;
}

.animation-delay-500 {
  animation-delay: 0.5s;
  animation-fill-mode: both;
}

.animation-delay-700 {
  animation-delay: 0.7s;
  animation-fill-mode: both;
}

.animation-delay-900 {
  animation-delay: 0.9s;
  animation-fill-mode: both;
}

.animation-delay-1000 {
  animation-delay: 1s;
  animation-fill-mode: both;
}

.animation-delay-1100 {
  animation-delay: 1.1s;
  animation-fill-mode: both;
}

.animation-delay-1200 {
  animation-delay: 1.2s;
  animation-fill-mode: both;
}

/* Enhanced hover effects */
.group:hover .group-hover\:scale-110 {
  transform: scale(1.1);
}

/* Backdrop blur support */
.backdrop-blur-lg {
  backdrop-filter: blur(16px);
}

.backdrop-blur-sm {
  backdrop-filter: blur(4px);
}

/* Custom gradient text */
.bg-clip-text {
  -webkit-background-clip: text;
  background-clip: text;
}

/* Glass morphism effect */
.bg-white\/80 {
  background-color: rgba(255, 255, 255, 0.8);
}

.bg-white\/50 {
  background-color: rgba(255, 255, 255, 0.5);
}

.border-white\/20 {
  border-color: rgba(255, 255, 255, 0.2);
}

/* Smooth transitions */
* {
  transition: all 0.2s ease;
}

/* Focus ring enhancement */
input:focus {
  outline: none;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

/* Button enhancement */
button:active {
  transform: scale(0.95);
}

/* Enhanced shadow */
.shadow-xl {
  box-shadow:
    0 20px 25px -5px rgba(0, 0, 0, 0.1),
    0 10px 10px -5px rgba(0, 0, 0, 0.04);
}
</style>
