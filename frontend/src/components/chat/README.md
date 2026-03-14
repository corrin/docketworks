# MCP Tool Details Components

This directory contains components for displaying MCP (Model Context Protocol) tool details in the quote/chat interface.

## Components

### McpToolDetails.vue

Main component that displays comprehensive tool information for AI assistant messages.

**Features:**

- Hidden by default with expandable tool count badge
- Performance optimized with lazy loading
- Handles large numbers of tool calls with virtualization
- Copy functionality for debugging
- Error boundaries for malformed metadata
- XSS protection

**Props:**

```typescript
interface Props {
  metadata?: Record<string, unknown> // Raw metadata from chat message
  defaultExpanded?: boolean // Whether to show expanded by default
}
```

**Usage:**

```vue
<McpToolDetails :metadata="message.metadata" :default-expanded="false" />
```

### ToolCallDisplay.vue

Component for displaying individual tool calls with arguments and results.

**Features:**

- Collapsible display of tool name, arguments, and results
- Copy individual tool data to clipboard
- JSON formatting for arguments
- Truncation indicators for long results
- XSS prevention

**Props:**

```typescript
interface Props {
  toolCall: ToolCall // Individual tool call data
}
```

**Usage:**

```vue
<ToolCallDisplay :tool-call="toolCall" />
```

## Data Structures

### ToolCall

```typescript
interface ToolCall {
  name: string // Tool name (e.g., "search_products")
  arguments: Record<string, any> // Tool arguments as key-value pairs
  result_preview: string // Truncated result (max 200 chars)
}
```

### McpMetadata

```typescript
interface McpMetadata {
  tool_calls?: ToolCall[] // Array of executed tool calls
  tool_definitions?: ToolDefinition[] // Available tools for session
  model?: string // AI model used (e.g., "gemini-1.5-pro")
  system_prompt?: string // System prompt used
  user_message?: string // Original user message
  chat_history?: any[] // Conversation history
}
```

## Integration

The components are integrated into `QuotingChatView.vue` and automatically show for assistant messages that contain metadata:

```vue
<!-- In QuotingChatView.vue -->
<div v-if="message.senderId !== currentUserId && message.metadata" class="mt-3">
  <McpToolDetails :metadata="message.metadata" />
</div>
```

## Validation

All metadata is validated using Zod schemas in `/src/schemas/mcp-tool-metadata.schema.ts`. Invalid metadata triggers error boundaries rather than crashes.

## Performance

- **Lazy Loading**: Tool details only load when expanded
- **Virtualization**: Large tool call lists (5+) use progressive loading
- **Memory Management**: Cleanup timers on component unmount
- **Debounced Interactions**: Smooth animations

## Security

- **XSS Prevention**: All user content sanitized before display
- **Input Validation**: Zod schemas prevent malformed data crashes
- **Error Boundaries**: Graceful degradation on validation failures

## Testing

Comprehensive test coverage in `__tests__/` directories:

- Unit tests for all components
- Integration tests with chat view
- Edge case handling (malformed data, XSS, Unicode)
- Performance validation

## Copy Functionality

Users can copy tool data for debugging:

- **Individual Tools**: Copy button on each tool call
- **Complete Metadata**: "Copy All" button in main component
- **Fallback Support**: Works in older browsers without Clipboard API
