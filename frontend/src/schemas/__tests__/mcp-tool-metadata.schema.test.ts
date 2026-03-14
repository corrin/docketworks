import { describe, it, expect } from 'vitest'
import {
  ToolCallSchema,
  ToolDefinitionSchema,
  McpMetadataSchema,
  parseMetadata,
  hasToolCalls,
  getToolCallCount,
  type ToolCall,
  type ToolDefinition,
  type McpMetadata,
} from '../mcp-tool-metadata.schema'

describe('MCP Tool Metadata Schema', () => {
  describe('ToolCallSchema', () => {
    it('validates valid tool call', () => {
      const validToolCall = {
        name: 'search_products',
        arguments: { query: 'steel sheet', category: 'metal' },
        result_preview: 'Found 15 products matching your search criteria...',
      }

      const result = ToolCallSchema.safeParse(validToolCall)
      expect(result.success).toBe(true)
      if (result.success) {
        expect(result.data.name).toBe('search_products')
        expect(result.data.arguments).toEqual({ query: 'steel sheet', category: 'metal' })
        expect(result.data.result_preview).toBe(
          'Found 15 products matching your search criteria...',
        )
      }
    })

    it('validates tool call with minimal data', () => {
      const minimalToolCall = {
        name: 'simple_tool',
      }

      const result = ToolCallSchema.safeParse(minimalToolCall)
      expect(result.success).toBe(true)
      if (result.success) {
        expect(result.data.name).toBe('simple_tool')
        expect(result.data.arguments).toEqual({})
        expect(result.data.result_preview).toBe('')
      }
    })

    it('rejects tool call with empty name', () => {
      const invalidToolCall = {
        name: '',
        arguments: {},
        result_preview: 'result',
      }

      const result = ToolCallSchema.safeParse(invalidToolCall)
      expect(result.success).toBe(false)
    })

    it('rejects tool call without name', () => {
      const invalidToolCall = {
        arguments: {},
        result_preview: 'result',
      }

      const result = ToolCallSchema.safeParse(invalidToolCall)
      expect(result.success).toBe(false)
    })

    it('handles various argument types', () => {
      const toolCallWithMixedArgs = {
        name: 'mixed_args_tool',
        arguments: {
          string: 'text',
          number: 42,
          boolean: true,
          array: [1, 2, 3],
          object: { nested: 'value' },
          null: null,
        },
        result_preview: 'result',
      }

      const result = ToolCallSchema.safeParse(toolCallWithMixedArgs)
      expect(result.success).toBe(true)
      if (result.success) {
        expect(result.data.arguments.string).toBe('text')
        expect(result.data.arguments.number).toBe(42)
        expect(result.data.arguments.boolean).toBe(true)
        expect(result.data.arguments.array).toEqual([1, 2, 3])
        expect(result.data.arguments.object).toEqual({ nested: 'value' })
        expect(result.data.arguments.null).toBeNull()
      }
    })
  })

  describe('ToolDefinitionSchema', () => {
    it('validates valid tool definition', () => {
      const validDefinition = {
        name: 'search_products',
        description: 'Search for products in the database',
        parameters: {
          type: 'object',
          properties: {
            query: { type: 'string' },
            category: { type: 'string' },
          },
        },
      }

      const result = ToolDefinitionSchema.safeParse(validDefinition)
      expect(result.success).toBe(true)
      if (result.success) {
        expect(result.data.name).toBe('search_products')
        expect(result.data.description).toBe('Search for products in the database')
        expect(result.data.parameters).toEqual(validDefinition.parameters)
      }
    })

    it('validates tool definition with minimal data', () => {
      const minimalDefinition = {
        name: 'simple_tool',
      }

      const result = ToolDefinitionSchema.safeParse(minimalDefinition)
      expect(result.success).toBe(true)
      if (result.success) {
        expect(result.data.name).toBe('simple_tool')
        expect(result.data.description).toBeUndefined()
        expect(result.data.parameters).toBeUndefined()
      }
    })

    it('rejects tool definition with empty name', () => {
      const invalidDefinition = {
        name: '',
        description: 'description',
      }

      const result = ToolDefinitionSchema.safeParse(invalidDefinition)
      expect(result.success).toBe(false)
    })
  })

  describe('McpMetadataSchema', () => {
    it('validates complete metadata', () => {
      const completeMetadata = {
        tool_calls: [
          {
            name: 'search_products',
            arguments: { query: 'steel' },
            result_preview: 'Found products',
          },
        ],
        tool_definitions: [
          {
            name: 'search_products',
            description: 'Search for products',
          },
        ],
        model: 'gemini-1.5-pro',
        system_prompt: 'You are a helpful assistant',
        user_message: 'Find steel products',
        chat_history: [
          { role: 'user', content: 'Hello' },
          { role: 'assistant', content: 'Hi there!' },
        ],
      }

      const result = McpMetadataSchema.safeParse(completeMetadata)
      expect(result.success).toBe(true)
      if (result.success) {
        expect(result.data.tool_calls).toHaveLength(1)
        expect(result.data.tool_definitions).toHaveLength(1)
        expect(result.data.model).toBe('gemini-1.5-pro')
        expect(result.data.system_prompt).toBe('You are a helpful assistant')
        expect(result.data.user_message).toBe('Find steel products')
        expect(result.data.chat_history).toHaveLength(2)
      }
    })

    it('validates empty metadata', () => {
      const emptyMetadata = {}

      const result = McpMetadataSchema.safeParse(emptyMetadata)
      expect(result.success).toBe(true)
      if (result.success) {
        expect(result.data.tool_calls).toEqual([])
        expect(result.data.tool_definitions).toEqual([])
        expect(result.data.model).toBeUndefined()
        expect(result.data.system_prompt).toBeUndefined()
        expect(result.data.user_message).toBeUndefined()
        expect(result.data.chat_history).toBeUndefined()
      }
    })

    it('validates partial metadata', () => {
      const partialMetadata = {
        tool_calls: [
          {
            name: 'test_tool',
            arguments: {},
            result_preview: 'test result',
          },
        ],
        model: 'gemini-1.5-pro',
      }

      const result = McpMetadataSchema.safeParse(partialMetadata)
      expect(result.success).toBe(true)
      if (result.success) {
        expect(result.data.tool_calls).toHaveLength(1)
        expect(result.data.tool_definitions).toEqual([])
        expect(result.data.model).toBe('gemini-1.5-pro')
        expect(result.data.system_prompt).toBeUndefined()
      }
    })

    it('rejects metadata with invalid tool_calls', () => {
      const invalidMetadata = {
        tool_calls: 'not-an-array',
        model: 'gemini-1.5-pro',
      }

      const result = McpMetadataSchema.safeParse(invalidMetadata)
      expect(result.success).toBe(false)
    })

    it('rejects metadata with invalid tool_definitions', () => {
      const invalidMetadata = {
        tool_definitions: 'not-an-array',
        model: 'gemini-1.5-pro',
      }

      const result = McpMetadataSchema.safeParse(invalidMetadata)
      expect(result.success).toBe(false)
    })
  })

  describe('parseMetadata function', () => {
    it('returns success for valid metadata', () => {
      const validMetadata = {
        tool_calls: [
          {
            name: 'test_tool',
            arguments: { query: 'test' },
            result_preview: 'test result',
          },
        ],
        model: 'gemini-1.5-pro',
      }

      const result = parseMetadata(validMetadata)
      expect(result.success).toBe(true)
      expect(result.data).toBeDefined()
      expect(result.error).toBeUndefined()
      expect(result.data?.tool_calls).toHaveLength(1)
      expect(result.data?.model).toBe('gemini-1.5-pro')
    })

    it('returns error for invalid metadata', () => {
      const invalidMetadata = {
        tool_calls: 'not-an-array',
        model: 123,
      }

      const result = parseMetadata(invalidMetadata)
      expect(result.success).toBe(false)
      expect(result.data).toBeUndefined()
      expect(result.error).toBeDefined()
      expect(result.error).toContain('Invalid metadata format')
    })

    it('handles null metadata', () => {
      const result = parseMetadata(null)
      expect(result.success).toBe(false)
      expect(result.error).toBeDefined()
    })

    it('handles undefined metadata', () => {
      const result = parseMetadata(undefined)
      expect(result.success).toBe(false)
      expect(result.error).toBeDefined()
    })

    it('handles non-object metadata', () => {
      const result = parseMetadata('not-an-object')
      expect(result.success).toBe(false)
      expect(result.error).toBeDefined()
    })

    it('provides detailed error messages', () => {
      const invalidMetadata = {
        tool_calls: [
          {
            name: '', // Empty name should fail
            arguments: {},
            result_preview: 'result',
          },
        ],
      }

      const result = parseMetadata(invalidMetadata)
      expect(result.success).toBe(false)
      expect(result.error).toContain('Tool name is required')
    })
  })

  describe('hasToolCalls function', () => {
    it('returns true for metadata with tool calls', () => {
      const metadataWithTools = {
        tool_calls: [
          {
            name: 'test_tool',
            arguments: {},
            result_preview: 'result',
          },
        ],
      }

      expect(hasToolCalls(metadataWithTools)).toBe(true)
    })

    it('returns false for metadata without tool calls', () => {
      const metadataWithoutTools = {
        model: 'gemini-1.5-pro',
      }

      expect(hasToolCalls(metadataWithoutTools)).toBe(false)
    })

    it('returns false for metadata with empty tool calls array', () => {
      const metadataWithEmptyTools = {
        tool_calls: [],
      }

      expect(hasToolCalls(metadataWithEmptyTools)).toBe(false)
    })

    it('returns false for invalid metadata', () => {
      const invalidMetadata = {
        tool_calls: 'not-an-array',
      }

      expect(hasToolCalls(invalidMetadata)).toBe(false)
    })

    it('returns false for null metadata', () => {
      expect(hasToolCalls(null)).toBe(false)
    })

    it('returns false for undefined metadata', () => {
      expect(hasToolCalls(undefined)).toBe(false)
    })
  })

  describe('getToolCallCount function', () => {
    it('returns correct count for metadata with tool calls', () => {
      const metadataWithTools = {
        tool_calls: [
          {
            name: 'tool1',
            arguments: {},
            result_preview: 'result1',
          },
          {
            name: 'tool2',
            arguments: {},
            result_preview: 'result2',
          },
        ],
      }

      expect(getToolCallCount(metadataWithTools)).toBe(2)
    })

    it('returns 0 for metadata without tool calls', () => {
      const metadataWithoutTools = {
        model: 'gemini-1.5-pro',
      }

      expect(getToolCallCount(metadataWithoutTools)).toBe(0)
    })

    it('returns 0 for metadata with empty tool calls array', () => {
      const metadataWithEmptyTools = {
        tool_calls: [],
      }

      expect(getToolCallCount(metadataWithEmptyTools)).toBe(0)
    })

    it('returns 0 for invalid metadata', () => {
      const invalidMetadata = {
        tool_calls: 'not-an-array',
      }

      expect(getToolCallCount(invalidMetadata)).toBe(0)
    })

    it('returns 0 for null metadata', () => {
      expect(getToolCallCount(null)).toBe(0)
    })

    it('returns 0 for undefined metadata', () => {
      expect(getToolCallCount(undefined)).toBe(0)
    })
  })

  describe('type safety', () => {
    it('provides correct TypeScript types', () => {
      const toolCall: ToolCall = {
        name: 'test_tool',
        arguments: { query: 'test' },
        result_preview: 'result',
      }

      const toolDefinition: ToolDefinition = {
        name: 'test_tool',
        description: 'Test tool',
        parameters: { type: 'object' },
      }

      const metadata: McpMetadata = {
        tool_calls: [toolCall],
        tool_definitions: [toolDefinition],
        model: 'gemini-1.5-pro',
        system_prompt: 'prompt',
        user_message: 'message',
        chat_history: [{ role: 'user', content: 'hello' }],
      }

      // These should compile without errors
      expect(toolCall.name).toBe('test_tool')
      expect(toolDefinition.name).toBe('test_tool')
      expect(metadata.model).toBe('gemini-1.5-pro')
    })
  })
})
