import { ref, computed } from 'vue'

/**
 * Device type preference (UI COMFORT - not permissions)
 *
 * Controls which UI variant to show: touch-friendly vs desktop-optimized.
 * User can override to get desktop features on mobile if they prefer.
 *
 * NOTE: This is different from `is_office_staff` which controls PERMISSIONS
 * (what the user can access). Device type controls PRESENTATION (how it looks).
 * Both have similar effects in practice, but different purposes.
 */

const detectedTouchDevice = 'ontouchstart' in window || navigator.maxTouchPoints > 0

// User can override their device type preference
const deviceOverride = ref<'computer' | 'touch' | null>(null)

export const isComputer = computed(() => {
  if (deviceOverride.value !== null) {
    return deviceOverride.value === 'computer'
  }
  return !detectedTouchDevice
})

export const isTouchscreen = computed(() => !isComputer.value)

export const detectedDeviceType = detectedTouchDevice ? 'touch' : 'computer'

export function setDevicePreference(preference: 'computer' | 'touch' | 'auto') {
  deviceOverride.value = preference === 'auto' ? null : preference
}
