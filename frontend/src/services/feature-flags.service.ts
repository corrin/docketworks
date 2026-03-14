// src/services/feature-flags.service.ts

/**
 * Feature Flags Service
 *
 * Centralized service for reading feature flags from environment variables.
 * Provides simple boolean values based on Vite environment variables.
 */
export class FeatureFlagsService {
  private static weekendEnabled: boolean | null = null
  private static lastChecked: number = 0
  private static readonly CACHE_DURATION = 5 * 60 * 1000 // 5 minutes

  /**
   * Check if weekend timesheets are enabled
   * Reads from VITE_WEEKEND_TIMESHEETS_ENABLED environment variable
   *
   * @returns true if weekend timesheets are enabled, false otherwise
   */
  static isWeekendTimesheetsEnabled(): boolean {
    // Check cache first
    const now = Date.now()
    if (this.weekendEnabled !== null && now - this.lastChecked < this.CACHE_DURATION) {
      return this.weekendEnabled
    }

    try {
      const envValue = import.meta.env.VITE_WEEKEND_TIMESHEETS_ENABLED
      console.log(
        `Reading VITE_WEEKEND_TIMESHEETS_ENABLED: "${envValue}" | Original value: ${import.meta.env.VITE_WEEKEND_TIMESHEETS_ENABLED}`,
      )

      // Handle undefined/null values
      if (envValue === undefined || envValue === null) {
        console.warn(
          'VITE_WEEKEND_TIMESHEETS_ENABLED environment variable is not set, defaulting to false',
        )
        this.weekendEnabled = false
        return false
      }

      // Convert string to boolean, default to false for any non-truthy values
      const stringValue = String(envValue).toLowerCase().trim()
      this.weekendEnabled =
        stringValue === 'true' ||
        stringValue === '1' ||
        stringValue === 'yes' ||
        stringValue === 'on'

      console.log(
        `Weekend timesheets feature flag: ${this.weekendEnabled ? 'ENABLED' : 'DISABLED'} (env: "${envValue}")`,
      )

      // Update cache timestamp
      this.lastChecked = now
      return this.weekendEnabled
    } catch (error) {
      console.error('Error reading weekend timesheets feature flag, defaulting to false:', error)
      this.weekendEnabled = false
      return false
    }
  }

  /**
   * Refresh feature flags (useful for testing or dynamic updates)
   * Clears cached values to force re-reading from environment
   */
  static refreshFlags(): void {
    this.weekendEnabled = null
    this.lastChecked = 0
  }

  /**
   * Clear the feature flags cache (useful for testing or forced refresh)
   */
  static clearCache(): void {
    this.weekendEnabled = null
    this.lastChecked = 0
  }

  /**
   * Get cache status for debugging and performance monitoring
   */
  static getCacheStatus(): { cached: boolean; age: number; value: boolean | null } {
    const now = Date.now()
    return {
      cached: this.weekendEnabled !== null,
      age: this.lastChecked > 0 ? now - this.lastChecked : 0,
      value: this.weekendEnabled,
    }
  }

  /**
   * Get all feature flags as an object
   * Useful for debugging or logging
   */
  static getAllFlags(): Record<string, boolean> {
    return {
      weekendTimesheets: this.isWeekendTimesheetsEnabled(),
    }
  }
}

// Export singleton instance for convenience
export const featureFlags = FeatureFlagsService
