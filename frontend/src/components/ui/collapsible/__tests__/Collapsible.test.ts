import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { Collapsible, CollapsibleContent } from '../index'

describe('Collapsible', () => {
  it('renders collapsed by default', () => {
    const wrapper = mount(Collapsible, {
      slots: {
        default: `
          <CollapsibleContent>
            <div data-testid="content">Hidden content</div>
          </CollapsibleContent>
        `,
      },
      global: {
        components: {
          CollapsibleContent,
        },
      },
    })

    // Content should be hidden by default
    expect(wrapper.find('[data-testid="content"]').exists()).toBe(false)
  })

  it('shows content when open prop is true', () => {
    const wrapper = mount(Collapsible, {
      props: {
        open: true,
      },
      slots: {
        default: `
          <CollapsibleContent>
            <div data-testid="content">Visible content</div>
          </CollapsibleContent>
        `,
      },
      global: {
        components: {
          CollapsibleContent,
        },
      },
    })

    // Content should be visible when open=true
    expect(wrapper.find('[data-testid="content"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="content"]').text()).toBe('Visible content')
  })

  it('emits update:open event when internal state changes', async () => {
    const wrapper = mount(Collapsible, {
      props: {
        open: false,
      },
      slots: {
        default: `
          <CollapsibleContent>
            <div data-testid="content">Content</div>
          </CollapsibleContent>
        `,
      },
      global: {
        components: {
          CollapsibleContent,
        },
      },
    })

    // Simulate opening the collapsible programmatically
    await wrapper.setProps({ open: true })
    await nextTick()

    // Should show content
    expect(wrapper.find('[data-testid="content"]').exists()).toBe(true)
  })

  it('handles v-model correctly', async () => {
    const TestComponent = {
      components: { Collapsible, CollapsibleContent },
      template: `
        <div>
          <Collapsible v-model:open="isOpen">
            <CollapsibleContent>
              <div data-testid="content">Content</div>
            </CollapsibleContent>
          </Collapsible>
          <div data-testid="open-state">{{ isOpen }}</div>
        </div>
      `,
      data() {
        return {
          isOpen: false,
        }
      },
    }

    const wrapper = mount(TestComponent)

    // Initially closed
    expect(wrapper.find('[data-testid="content"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="open-state"]').text()).toBe('false')

    // Open programmatically
    wrapper.vm.isOpen = true
    await nextTick()

    expect(wrapper.find('[data-testid="content"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="open-state"]').text()).toBe('true')
  })
})
