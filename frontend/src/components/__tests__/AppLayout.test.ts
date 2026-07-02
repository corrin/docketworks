import { enableAutoUnmount, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const route = reactive<{ meta: { allowScroll?: boolean } }>({
  meta: {},
})

vi.mock('vue-router', () => ({
  useRoute: () => route,
}))

vi.mock('../AppNavbar.vue', () => ({
  default: { template: '<nav data-test="navbar" />' },
}))

import AppLayout from '../AppLayout.vue'

enableAutoUnmount(afterEach)

describe('AppLayout scrolling', () => {
  beforeEach(() => {
    route.meta = {}
    document.body.style.overflowY = ''
    document.documentElement.style.overflowY = ''
  })

  it('allows vertical scrolling by default', () => {
    const wrapper = mount(AppLayout, {
      slots: {
        default: '<div>Page content</div>',
      },
    })

    expect(wrapper.find('main').classes()).toContain('overflow-y-auto')
    expect(wrapper.find('main').classes()).not.toContain('overflow-y-hidden')
    expect(document.body.style.overflowY).toBe('auto')
    expect(document.documentElement.style.overflowY).toBe('auto')
  })

  it('hides vertical scrolling only when route meta opts out', () => {
    route.meta = { allowScroll: false }

    const wrapper = mount(AppLayout, {
      slots: {
        default: '<div>Fixed workspace</div>',
      },
    })

    expect(wrapper.find('main').classes()).toContain('overflow-y-hidden')
    expect(wrapper.find('main').classes()).not.toContain('overflow-y-auto')
    expect(document.body.style.overflowY).toBe('hidden')
    expect(document.documentElement.style.overflowY).toBe('hidden')
  })
})
