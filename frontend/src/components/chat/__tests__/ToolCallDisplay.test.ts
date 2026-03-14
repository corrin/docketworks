import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import ToolCallDisplay from '../ToolCallDisplay.vue'
import type { ToolCall } from '@/schemas/mcp-tool-metadata.schema'

// Mock clipboard API using vi.stubGlobal for read-only properties
beforeEach(() => {
  const mockClipboard = {
    writeText: vi.fn().mockResolvedValue(undefined),
    readText: vi.fn().mockResolvedValue(''),
  }
  vi.stubGlobal('navigator', {
    ...navigator,
    clipboard: mockClipboard,
  })
})

describe('ToolCallDisplay', () => {
  const mockToolCall: ToolCall = {
    name: 'search_products',
    arguments: {
      query: 'steel sheet',
      category: 'metal',
      limit: 10,
    },
    result_preview:
      'Found 15 products matching your search criteria. Top results include: 1. Steel Sheet 2mm - $12.50/sq ft, 2. Steel Sheet 3mm - $15.00/sq ft...',
  }

  // Helper to find elements by data-automation-id
  const autoId = (wrapper: ReturnType<typeof mount>, id: string) =>
    wrapper.find(`[data-automation-id="${id}"]`)

  const findExpandButton = (wrapper: ReturnType<typeof mount>) =>
    autoId(wrapper, 'ToolCallDisplay-toggle')

  describe('basic rendering', () => {
    it('displays tool name correctly', () => {
      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: mockToolCall,
        },
      })

      expect(wrapper.text()).toContain('search_products')
      expect(wrapper.text()).toContain('Tool Call')
    })

    it('starts collapsed by default', () => {
      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: mockToolCall,
        },
      })

      // Details should be hidden initially - check that Arguments/Result text is not visible
      expect(wrapper.text()).not.toContain('Arguments')
      expect(wrapper.text()).not.toContain('Result Preview')
    })

    it('expands when clicked', async () => {
      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: mockToolCall,
        },
      })

      // Click the expand button
      await findExpandButton(wrapper).trigger('click')

      // Details should now be visible
      expect(wrapper.text()).toContain('Arguments')
      expect(wrapper.text()).toContain('Result Preview')
    })

    it('toggles chevron icon on expand/collapse', async () => {
      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: mockToolCall,
        },
      })

      // Find the ChevronDown icon by data-automation-id
      const getChevron = () => autoId(wrapper, 'ToolCallDisplay-chevron')

      // Initially not rotated
      expect(getChevron().classes()).not.toContain('rotate-180')

      // Click to expand
      await findExpandButton(wrapper).trigger('click')
      expect(getChevron().classes()).toContain('rotate-180')

      // Click to collapse
      await findExpandButton(wrapper).trigger('click')
      expect(getChevron().classes()).not.toContain('rotate-180')
    })
  })

  describe('arguments display', () => {
    it('displays formatted arguments correctly', async () => {
      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: mockToolCall,
        },
      })

      await findExpandButton(wrapper).trigger('click')

      const argumentsSection = wrapper.find('pre')
      expect(argumentsSection.exists()).toBe(true)

      // Check that JSON is formatted
      expect(argumentsSection.text()).toContain('"query": "steel sheet"')
      expect(argumentsSection.text()).toContain('"category": "metal"')
      expect(argumentsSection.text()).toContain('"limit": 10')
    })

    it('handles empty arguments', async () => {
      const toolCallWithEmptyArgs: ToolCall = {
        name: 'no_args_tool',
        arguments: {},
        result_preview: 'Some result',
      }

      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: toolCallWithEmptyArgs,
        },
      })

      await findExpandButton(wrapper).trigger('click')

      // Should still show the result section
      expect(wrapper.text()).toContain('Result Preview')
      expect(wrapper.text()).toContain('Some result')
    })

    it('handles malformed arguments gracefully', async () => {
      const toolCallWithBadArgs: ToolCall = {
        name: 'bad_args_tool',
        arguments: { circular: null } as Record<string, unknown>,
        result_preview: 'Some result',
      }

      // Create circular reference to test JSON.stringify error handling
      toolCallWithBadArgs.arguments.circular = toolCallWithBadArgs.arguments

      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: toolCallWithBadArgs,
        },
      })

      await findExpandButton(wrapper).trigger('click')

      // Should not crash and should show something
      expect(wrapper.exists()).toBe(true)
    })
  })

  describe('result preview display', () => {
    it('displays result preview correctly', async () => {
      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: mockToolCall,
        },
      })

      await findExpandButton(wrapper).trigger('click')

      expect(wrapper.text()).toContain('Result Preview')
      expect(wrapper.text()).toContain('Found 15 products matching your search criteria')
    })

    it('shows truncation indicator for long results', async () => {
      const longResult = 'A'.repeat(200) // Exactly 200 characters
      const toolCallWithLongResult: ToolCall = {
        name: 'long_result_tool',
        arguments: {},
        result_preview: longResult,
      }

      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: toolCallWithLongResult,
        },
      })

      await findExpandButton(wrapper).trigger('click')

      expect(wrapper.text()).toContain('Result truncated to 200 characters')
    })

    it('does not show truncation indicator for short results', async () => {
      const shortResult = 'Short result'
      const toolCallWithShortResult: ToolCall = {
        name: 'short_result_tool',
        arguments: {},
        result_preview: shortResult,
      }

      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: toolCallWithShortResult,
        },
      })

      await findExpandButton(wrapper).trigger('click')

      expect(wrapper.text()).not.toContain('Result truncated')
    })

    it('handles empty result preview', async () => {
      const toolCallWithEmptyResult: ToolCall = {
        name: 'empty_result_tool',
        arguments: { query: 'test' },
        result_preview: '',
      }

      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: toolCallWithEmptyResult,
        },
      })

      await findExpandButton(wrapper).trigger('click')

      // Should show arguments but handle empty result gracefully
      expect(wrapper.text()).toContain('Arguments')
      expect(wrapper.text()).toContain('"query": "test"')
    })
  })

  describe('edge cases and error handling', () => {
    it('handles tool call with minimal data', () => {
      const minimalToolCall: ToolCall = {
        name: 'minimal_tool',
        arguments: {},
        result_preview: '',
      }

      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: minimalToolCall,
        },
      })

      expect(wrapper.text()).toContain('minimal_tool')
      expect(wrapper.exists()).toBe(true)
    })

    it('displays no data message when no arguments or results', async () => {
      const emptyToolCall: ToolCall = {
        name: 'empty_tool',
        arguments: {},
        result_preview: '',
      }

      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: emptyToolCall,
        },
      })

      await findExpandButton(wrapper).trigger('click')

      expect(wrapper.text()).toContain('No additional details available')
    })

    it('handles very long tool names', () => {
      const longNameToolCall: ToolCall = {
        name: 'very_long_tool_name_that_should_be_handled_gracefully_without_breaking_the_layout_or_causing_overflow_issues',
        arguments: {},
        result_preview: 'Result',
      }

      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: longNameToolCall,
        },
      })

      expect(wrapper.exists()).toBe(true)
      expect(wrapper.text()).toContain('very_long_tool_name')
    })
  })

  describe('XSS prevention', () => {
    it('prevents XSS in result preview', async () => {
      const xssToolCall: ToolCall = {
        name: 'xss_tool',
        arguments: {},
        result_preview:
          '<script>alert("xss")</script><img src="x" onerror="alert(1)">Malicious content',
      }

      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: xssToolCall,
        },
      })

      await findExpandButton(wrapper).trigger('click')

      // Vue escapes HTML in templates, so script tags become &lt;script&gt;
      // The component also strips HTML tags from result_preview
      // Check that no actual <script> or <img> elements exist
      expect(wrapper.find('script').exists()).toBe(false)
      expect(wrapper.find('img[onerror]').exists()).toBe(false)

      // Should contain safe text content (after HTML stripping)
      expect(wrapper.text()).toContain('Malicious content')
    })

    it('prevents XSS in tool name', () => {
      const xssToolCall: ToolCall = {
        name: '<script>alert("xss")</script>dangerous_tool',
        arguments: {},
        result_preview: 'Safe result',
      }

      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: xssToolCall,
        },
      })

      // Vue's template interpolation escapes HTML, so no actual script element should exist
      expect(wrapper.find('script').exists()).toBe(false)
      // The escaped text should be in the HTML as &lt;script&gt; but not executable
      expect(wrapper.text()).toContain('dangerous_tool')
    })

    it('handles Unicode and special characters safely', async () => {
      const unicodeToolCall: ToolCall = {
        name: 'unicode_tool_测试',
        arguments: {
          query: '测试中文字符',
          symbols: '!@#$%^&*()_+-=[]{}|;:,.<>?',
          emoji: '🔧⚙️🛠️',
        },
        result_preview: 'Results with émojis 🔧⚙️🛠️ and symbols !@#$%^&*()',
      }

      const wrapper = mount(ToolCallDisplay, {
        props: {
          toolCall: unicodeToolCall,
        },
      })

      // Check tool name is displayed
      expect(wrapper.text()).toContain('unicode_tool_测试')

      // Expand to see arguments
      await findExpandButton(wrapper).trigger('click')

      // Check Unicode content in expanded section
      expect(wrapper.text()).toContain('测试中文字符')
      expect(wrapper.text()).toContain('🔧⚙️🛠️')
      expect(wrapper.text()).toContain('!@#$%^&*()')
    })
  })
})
