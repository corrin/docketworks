import { useCalendarStore } from '@kodeglot/vue-calendar'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

describe('workshop calendar store integration', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('uses the application Pinia instance', () => {
    const calendarStore = useCalendarStore()

    expect(calendarStore.currentDate).toBeInstanceOf(Date)
  })
})
