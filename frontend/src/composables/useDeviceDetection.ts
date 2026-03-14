import { ref, computed, onMounted, onUnmounted } from 'vue'
import { debugLog } from '@/utils/debug'

export function useDeviceDetection() {
  const windowWidth = ref(window.innerWidth)
  const windowHeight = ref(window.innerHeight)

  const updateDimensions = () => {
    windowWidth.value = window.innerWidth
    windowHeight.value = window.innerHeight
  }

  onMounted(() => {
    window.addEventListener('resize', updateDimensions)
  })

  onUnmounted(() => {
    window.removeEventListener('resize', updateDimensions)
  })

  const isMobile = computed(() => {
    return windowWidth.value <= 430 && windowHeight.value <= 932
  })

  const isTablet = computed(() => {
    const isTabletDimensions =
      windowWidth.value <= 1024 &&
      windowHeight.value <= 1366 &&
      !(windowWidth.value <= 430 && windowHeight.value <= 932)

    debugLog('Device detection:', {
      windowWidth: windowWidth.value,
      windowHeight: windowHeight.value,
      isTabletDimensions,
      isMobile: windowWidth.value <= 430 && windowHeight.value <= 932,
      range: 'Tablet: up to 1024x1366, Mobile: up to 430x932',
    })

    return isTabletDimensions
  })

  const isDesktop = computed(() => {
    return !isMobile.value && !isTablet.value
  })

  const isTouchDevice = computed(() => {
    return 'ontouchstart' in window || navigator.maxTouchPoints > 0
  })

  const isIpad = computed(() => {
    const userAgent = navigator.userAgent.toLowerCase()
    return (
      userAgent.includes('ipad') ||
      (userAgent.includes('macintosh') && navigator.maxTouchPoints > 1)
    )
  })

  const getDragConfig = () => {
    return {
      delay: 0,
      touchStartThreshold: 0,
      forceFallback: false,
      filter: '.no-drag',
      preventOnFilter: true,
      disabled: false,

      fallbackOnBody: true,
      swapThreshold: 0.65,
      dragoverBubble: false,
      removeCloneOnHide: false,
      emptyInsertThreshold: 5,
    }
  }

  const getStaffDragConfig = () => {
    return {
      delay: 0,
      touchStartThreshold: 0,
      forceFallback: false,
      filter: '.no-drag',
      preventOnFilter: true,
      disabled: false,

      fallbackOnBody: true,
      swapThreshold: 0.65,
      dragoverBubble: false,
      removeCloneOnHide: false,
      emptyInsertThreshold: 5,
    }
  }

  return {
    windowWidth,
    windowHeight,
    isMobile,
    isTablet,
    isDesktop,
    isTouchDevice,
    isIpad,
    getDragConfig,
    getStaffDragConfig,
  }
}
