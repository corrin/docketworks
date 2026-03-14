import { z } from 'zod'

/**
 * Validation schema for individual MCP tool calls
 */
export const ToolCallSchema = z.object({
  name: z.string().min(1, 'Tool name is required'),
  arguments: z.record(z.any()).default({}),
  result_preview: z.string().default(''),
})

/**
 * Validation schema for MCP tool definitions
 */
export const ToolDefinitionSchema = z.object({
  name: z.string().min(1, 'Tool definition name is required'),
  description: z.string().optional(),
  parameters: z.record(z.any()).optional(),
})

/**
 * Validation schema for complete MCP metadata from assistant messages
 */
export const McpMetadataSchema = z.object({
  tool_calls: z.array(ToolCallSchema).optional().default([]),
  tool_definitions: z.array(ToolDefinitionSchema).optional().default([]),
  model: z.string().optional(),
  system_prompt: z.string().optional(),
  user_message: z.string().optional(),
  chat_history: z.array(z.any()).optional(),
})

/**
 * Type definitions derived from schemas
 */
export type ToolCall = z.infer<typeof ToolCallSchema>
export type ToolDefinition = z.infer<typeof ToolDefinitionSchema>
export type McpMetadata = z.infer<typeof McpMetadataSchema>

/**
 * Validation result wrapper
 */
export interface ValidationResult<T> {
  success: boolean
  data?: T
  error?: string
}

/**
 * Safely parse and validate MCP metadata
 */
export function parseMetadata(metadata: unknown): ValidationResult<McpMetadata> {
  try {
    const parsed = McpMetadataSchema.parse(metadata)
    return {
      success: true,
      data: parsed,
    }
  } catch (error) {
    if (error instanceof z.ZodError) {
      return {
        success: false,
        error: `Invalid metadata format: ${error.issues.map((i) => i.message).join(', ')}`,
      }
    }
    return {
      success: false,
      error: 'Unknown validation error',
    }
  }
}

/**
 * Check if metadata contains tool calls
 */
export function hasToolCalls(metadata: unknown): boolean {
  const result = parseMetadata(metadata)
  return result.success && (result.data?.tool_calls?.length ?? 0) > 0
}

/**
 * Get tool call count from metadata
 */
export function getToolCallCount(metadata: unknown): number {
  const result = parseMetadata(metadata)
  return result.success ? (result.data?.tool_calls?.length ?? 0) : 0
}
