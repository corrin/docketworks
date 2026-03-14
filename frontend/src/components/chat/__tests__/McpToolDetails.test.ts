import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import McpToolDetails from '../McpToolDetails.vue'
import type { McpMetadata } from '@/schemas/mcp-tool-metadata.schema'

describe('McpToolDetails', () => {
  const mockValidMetadata: McpMetadata = {
    tool_calls: [
      {
        name: 'search_products',
        arguments: { query: 'steel sheet', category: 'metal' },
        result_preview: 'Found 15 products matching your search criteria...',
      },
      {
        name: 'get_pricing_for_material',
        arguments: { material: 'steel', thickness: '2mm' },
        result_preview: 'Pricing for 2mm steel sheet: $12.50/sq ft...',
      },
    ],
    tool_definitions: [
      {
        name: 'search_products',
        description: 'Search for products in the database',
      },
      {
        name: 'get_pricing_for_material',
        description: 'Get pricing information for materials',
      },
    ],
    model: 'gemini-1.5-pro',
    system_prompt: 'You are a helpful assistant for metal fabrication quotes.',
    user_message: 'I need pricing for steel sheets',
  }

  describe('with valid metadata', () => {
    it('displays tool call count correctly', () => {
      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: mockValidMetadata,
        },
      })

      const toolSummary = wrapper.find('.tool-summary')
      expect(toolSummary.exists()).toBe(true)
      expect(toolSummary.text()).toContain('2 tools')
    })

    it('shows tool details when expanded', async () => {
      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: mockValidMetadata,
          defaultExpanded: true,
        },
      })

      await wrapper.vm.$nextTick()

      // Check that tool details content is visible
      expect(wrapper.find('.tool-details-content').exists()).toBe(true)

      // Check model information
      expect(wrapper.text()).toContain('gemini-1.5-pro')

      // Check tool definitions
      expect(wrapper.text()).toContain('search_products')
      expect(wrapper.text()).toContain('get_pricing_for_material')
    })

    it('toggles tool details visibility', async () => {
      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: mockValidMetadata,
        },
      })

      // Initially collapsed
      expect(wrapper.find('.tool-details-content').exists()).toBe(false)

      // Click to expand
      await wrapper.find('button').trigger('click')
      expect(wrapper.find('.tool-details-content').exists()).toBe(true)

      // Click to collapse
      await wrapper.find('button').trigger('click')
      expect(wrapper.find('.tool-details-content').exists()).toBe(false)
    })

    it('shows correct tool call count in singular and plural', () => {
      // Test singular
      const singleToolMetadata = {
        tool_calls: [mockValidMetadata.tool_calls![0]],
      }
      const singleWrapper = mount(McpToolDetails, {
        props: {
          metadata: singleToolMetadata,
        },
      })
      expect(singleWrapper.text()).toContain('1 tool')

      // Test plural
      const pluralWrapper = mount(McpToolDetails, {
        props: {
          metadata: mockValidMetadata,
        },
      })
      expect(pluralWrapper.text()).toContain('2 tools')
    })

    it('shows advanced details when toggled', async () => {
      vi.useFakeTimers()

      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: mockValidMetadata,
          defaultExpanded: true,
        },
      })

      // Wait for the 100ms loading delay in the component
      await vi.advanceTimersByTimeAsync(150)
      await wrapper.vm.$nextTick()

      // System prompt should be hidden initially (advanced details collapsed)
      expect(wrapper.text()).not.toContain('You are a helpful assistant')

      // Click show advanced using data-automation-id
      const advancedButton = wrapper.find('[data-automation-id="McpToolDetails-toggle-advanced"]')
      await advancedButton.trigger('click')
      await wrapper.vm.$nextTick()

      // System prompt should now be visible
      expect(wrapper.text()).toContain('You are a helpful assistant')

      vi.useRealTimers()
    })
  })

  describe('with invalid metadata', () => {
    it('shows error state for malformed metadata', () => {
      const invalidMetadata = {
        tool_calls: 'not-an-array', // Invalid type
        model: 123, // Invalid type
      }

      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: invalidMetadata,
        },
      })

      expect(wrapper.find('.error-state').exists()).toBe(true)
      expect(wrapper.text()).toContain('Tool details unavailable')
    })

    it('shows error message for validation errors', () => {
      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: { tool_calls: 'invalid' },
        },
      })

      const errorState = wrapper.find('.error-state')
      expect(errorState.exists()).toBe(true)
      expect(errorState.text()).toContain('Invalid metadata format')
    })
  })

  describe('with missing metadata', () => {
    it('does not render anything when metadata is undefined', () => {
      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: undefined,
        },
      })

      expect(wrapper.find('.tool-summary').exists()).toBe(false)
      expect(wrapper.find('.error-state').exists()).toBe(false)
    })

    it('does not render anything when metadata is empty', () => {
      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: {},
        },
      })

      expect(wrapper.find('.tool-summary').exists()).toBe(false)
      expect(wrapper.find('.error-state').exists()).toBe(false)
    })
  })

  describe('with partial metadata', () => {
    it('handles metadata with only tool_calls', () => {
      const partialMetadata = {
        tool_calls: [mockValidMetadata.tool_calls![0]],
      }

      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: partialMetadata,
        },
      })

      expect(wrapper.find('.tool-summary').exists()).toBe(true)
      expect(wrapper.text()).toContain('1 tool')
    })

    it('handles metadata with empty tool_calls array', () => {
      const emptyMetadata = {
        tool_calls: [],
        model: 'gemini-1.5-pro',
      }

      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: emptyMetadata,
        },
      })

      expect(wrapper.find('.tool-summary').exists()).toBe(false)
      expect(wrapper.find('.error-state').exists()).toBe(false)
    })
  })

  describe('security and XSS prevention', () => {
    it('prevents XSS in tool result previews', () => {
      const xssMetadata = {
        tool_calls: [
          {
            name: 'test_tool',
            arguments: {},
            result_preview: '<script>alert("xss")</script>Malicious content',
          },
        ],
      }

      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: xssMetadata,
          defaultExpanded: true,
        },
      })

      // Should not contain script tags
      expect(wrapper.html()).not.toContain('<script>')
      expect(wrapper.html()).not.toContain('alert("xss")')
    })

    it('sanitizes HTML in system prompt', () => {
      const htmlMetadata = {
        tool_calls: [
          {
            name: 'test_tool',
            arguments: {},
            result_preview: 'Safe content',
          },
        ],
        system_prompt: '<img src="x" onerror="alert(1)">Prompt with HTML',
      }

      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: htmlMetadata,
          defaultExpanded: true,
        },
      })

      // Show advanced to see system prompt
      const advancedButton = wrapper.find('button:last-child')
      advancedButton.trigger('click')

      // Should contain safe text but not HTML
      expect(wrapper.html()).not.toContain('<img')
      expect(wrapper.html()).not.toContain('onerror')
    })
  })

  describe('edge cases', () => {
    it('handles tool calls with missing fields', () => {
      const incompleteMetadata = {
        tool_calls: [
          {
            name: 'incomplete_tool',
            // Missing arguments and result_preview
          },
        ],
      }

      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: incompleteMetadata,
        },
      })

      expect(wrapper.find('.tool-summary').exists()).toBe(true)
      expect(wrapper.text()).toContain('1 tool')
    })

    it('handles very long tool names', () => {
      const longNameMetadata = {
        tool_calls: [
          {
            name: 'very_long_tool_name_that_should_be_handled_gracefully_without_breaking_layout',
            arguments: {},
            result_preview: 'Result',
          },
        ],
      }

      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: longNameMetadata,
        },
      })

      expect(wrapper.find('.tool-summary').exists()).toBe(true)
    })

    it('handles Unicode characters in tool data', async () => {
      vi.useFakeTimers()

      const unicodeMetadata = {
        tool_calls: [
          {
            name: 'unicode_tool',
            arguments: { query: '测试中文字符' },
            result_preview: 'Results with émojis 🔧⚙️🛠️',
          },
        ],
      }

      const wrapper = mount(McpToolDetails, {
        props: {
          metadata: unicodeMetadata,
          defaultExpanded: true,
        },
      })

      // Wait for the 100ms loading delay
      await vi.advanceTimersByTimeAsync(150)
      await wrapper.vm.$nextTick()

      expect(wrapper.find('.tool-summary').exists()).toBe(true)
      // Tool name is visible in expanded view
      expect(wrapper.text()).toContain('unicode_tool')

      vi.useRealTimers()
    })
  })
})
