import { ref, computed } from 'vue'

export interface ValidationRule<T = unknown> {
  test: (value: T) => boolean
  message: string
}

export interface ValidationErrors {
  [key: string]: string
}

export const useFormValidation = <T extends Record<string, unknown>>(formData: T) => {
  const errors = ref<ValidationErrors>({})
  const rules = ref<Record<keyof T, ValidationRule[]>>({} as Record<keyof T, ValidationRule[]>)

  const isValid = computed(() => {
    return Object.values(errors.value).every((error) => !error)
  })

  const setRules = (fieldRules: Record<keyof T, ValidationRule[]>) => {
    rules.value = fieldRules
  }

  const validateField = (field: keyof T): boolean => {
    const fieldRules = rules.value[field] || []
    const value = formData[field]

    for (const rule of fieldRules) {
      if (!rule.test(value)) {
        errors.value[field as string] = rule.message
        return false
      }
    }

    errors.value[field as string] = ''
    return true
  }

  const validateAll = (): boolean => {
    let allValid = true

    for (const field in rules.value) {
      if (!validateField(field)) {
        allValid = false
      }
    }

    return allValid
  }

  const clearErrors = () => {
    errors.value = {}
  }

  const clearError = (field: keyof T) => {
    errors.value[field as string] = ''
  }

  return {
    errors,
    isValid,
    setRules,
    validateField,
    validateAll,
    clearErrors,
    clearError,
  }
}

export const validationRules = {
  required: (message = 'This field is required'): ValidationRule => ({
    test: (value: unknown) => {
      if (typeof value === 'string') return value.trim().length > 0
      if (typeof value === 'number') return value > 0
      return value != null && value !== ''
    },
    message,
  }),

  minValue: (min: number, message?: string): ValidationRule<number> => ({
    test: (value: number) => value >= min,
    message: message || `Value must be at least ${min}`,
  }),

  maxValue: (max: number, message?: string): ValidationRule<number> => ({
    test: (value: number) => value <= max,
    message: message || `Value must be at most ${max}`,
  }),

  minLength: (min: number, message?: string): ValidationRule<string> => ({
    test: (value: string) => value.trim().length >= min,
    message: message || `Must be at least ${min} characters`,
  }),

  maxLength: (max: number, message?: string): ValidationRule<string> => ({
    test: (value: string) => value.trim().length <= max,
    message: message || `Must be at most ${max} characters`,
  }),
}
