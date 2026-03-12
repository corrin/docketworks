"""
MCP Chat Service (LiteLLM)

Handles AI-powered chat responses using the Model Context Protocol (MCP)
for accessing supplier data, pricing, and job context in chat conversations.

This service integrates:
- LiteLLM for provider-agnostic LLM access
- MCP tools for supplier/pricing data access
- JobQuoteChat model for conversation persistence
- Streaming response support
"""

import json
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional

from django.db import transaction

from apps.job.models import Job, JobQuoteChat
from apps.quoting.mcp import QuotingTool, SupplierProductQueryTool
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class MCPChatService:
    """
    Service for handling AI chat responses with MCP tool integration.

    Connects the chat system to AI providers and MCP tools for intelligent
    responses about pricing, suppliers, and job context.
    """

    def __init__(self) -> None:
        self.quoting_tool = QuotingTool()
        self.query_tool = SupplierProductQueryTool()

    def get_llm_service(self) -> LLMService:
        """Get configured LLMService instance."""
        return LLMService()

    def _get_system_prompt(self, job: Job) -> str:
        """Generate system prompt with job context and MCP tool descriptions."""
        company = CompanyDefaults.get_solo()
        return f"""You are an intelligent quoting assistant for {company.company_name},
a sheet metal jobbing shop.

Current Job Context:
- Job: {job.name}
- Client: {job.client.name}
- Status: {job.get_status_display()}
- Description: {job.description or 'No description available'}

You have access to the following tools to help with quoting and material sourcing:

1. **search_products**: Search supplier products by description or specifications
   - Use this to find specific materials or products
   - Example: search_products("steel sheet 4x8")

2. **get_pricing_for_material**: Get pricing information for specific materials with dimensions
   - Use this to get current market pricing
   - Example: get_pricing_for_material("aluminum", "4x8")

3. **create_quote_estimate**: Create a detailed quote estimate for a job
   - Use this to generate comprehensive quotes with materials and labor
   - Example: create_quote_estimate("{job.id}", "steel sheet, welding", 10.5)

4. **get_supplier_status**: Check supplier information and scraping status
   - Use this to verify supplier availability and data freshness
   - Example: get_supplier_status("Evans Ltd")

5. **compare_suppliers**: Compare pricing across multiple suppliers for materials
   - Use this to find the best pricing options
   - Example: compare_suppliers("steel angle")

Always be helpful, professional, and specific in your responses. When providing
pricing or material recommendations, explain your reasoning and mention any relevant
supplier information."""

    def _get_mcp_tools(self) -> List[Dict[str, Any]]:
        """Define MCP tools in OpenAI format for LiteLLM."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_products",
                    "description": "Search supplier products by description or specs",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search term for products",
                            },
                            "supplier_name": {
                                "type": "string",
                                "description": "Optional supplier name filter",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_pricing_for_material",
                    "description": "Get pricing information for specific materials",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "material_type": {
                                "type": "string",
                                "description": "Type of material (e.g., steel, aluminum)",
                            },
                            "dimensions": {
                                "type": "string",
                                "description": "Optional dimensions specification",
                            },
                        },
                        "required": ["material_type"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "create_quote_estimate",
                    "description": "Create a quote estimate for a job",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "job_id": {
                                "type": "string",
                                "description": "Job ID to create quote for",
                            },
                            "materials": {
                                "type": "string",
                                "description": "Description of materials needed",
                            },
                            "labor_hours": {
                                "type": "number",
                                "description": "Estimated labor hours",
                            },
                        },
                        "required": ["job_id", "materials"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_supplier_status",
                    "description": "Get status of supplier scraping and price lists",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "supplier_name": {
                                "type": "string",
                                "description": "Optional supplier name filter",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "compare_suppliers",
                    "description": "Compare pricing across suppliers for materials",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "material_query": {
                                "type": "string",
                                "description": "Material to compare prices for",
                            },
                        },
                        "required": ["material_query"],
                    },
                },
            },
        ]

    def _execute_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute MCP tool and return result."""
        try:
            if tool_name == "search_products":
                return self.quoting_tool.search_products(
                    arguments["query"], arguments.get("supplier_name") or ""
                )
            elif tool_name == "get_pricing_for_material":
                return self.quoting_tool.get_pricing_for_material(
                    arguments["material_type"], arguments.get("dimensions") or ""
                )
            elif tool_name == "create_quote_estimate":
                return self.quoting_tool.create_quote_estimate(
                    arguments["job_id"],
                    arguments["materials"],
                    arguments.get("labor_hours") or 0.0,
                )
            elif tool_name == "get_supplier_status":
                return self.quoting_tool.get_supplier_status(
                    arguments.get("supplier_name") or ""
                )
            elif tool_name == "compare_suppliers":
                return self.quoting_tool.compare_suppliers(arguments["material_query"])
            else:
                return f"Unknown tool: {tool_name}"

        except Exception as e:
            logger.error(f"MCP tool execution failed for {tool_name}: {e}")
            return f"Error executing {tool_name}: {str(e)}"

    @transaction.atomic
    def generate_ai_response(
        self,
        job_id: str,
        user_message: str,
        stream_callback: Optional[Callable[..., None]] = None,
    ) -> JobQuoteChat:
        """
        Generate AI response using LiteLLM with MCP tools.

        Args:
            job_id: UUID of the job for context
            user_message: User's message content
            stream_callback: Optional callback for streaming updates

        Returns:
            JobQuoteChat: The created assistant message
        """
        try:
            # Get job for context
            job = Job.objects.get(id=job_id)

            # Get LLM service
            llm = self.get_llm_service()

            # Get recent chat history for context
            recent_messages = JobQuoteChat.objects.filter(job=job).order_by(
                "-timestamp"
            )[:10]

            # Build conversation messages
            messages = [{"role": "system", "content": self._get_system_prompt(job)}]

            for msg in reversed(list(recent_messages)):
                messages.append({"role": msg.role, "content": msg.content})

            # Add current user message
            messages.append({"role": "user", "content": user_message})

            # Get tools
            tools = self._get_mcp_tools()

            # Create assistant message for streaming
            assistant_message = JobQuoteChat.objects.create(
                job=job,
                message_id=f"assistant-{uuid.uuid4()}",
                role="assistant",
                content="",
                metadata={"streaming": True, "tool_uses": []},
            )

            # Process with streaming if callback provided
            if stream_callback:
                current_content = ""
                tool_uses = []

                # Make streaming LLM call
                response = llm.completion(
                    messages=messages,
                    tools=tools,
                    stream=True,
                )

                # Process streaming chunks
                collected_tool_calls = {}

                for chunk in response:
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if not delta:
                        continue

                    # Accumulate content
                    if delta.content:
                        current_content += delta.content
                        assistant_message.content = current_content
                        assistant_message.save(update_fields=["content"])
                        stream_callback(assistant_message)

                    # Accumulate tool calls
                    if delta.tool_calls:
                        for tc in delta.tool_calls:
                            idx = tc.index
                            if idx not in collected_tool_calls:
                                collected_tool_calls[idx] = {
                                    "id": tc.id or "",
                                    "name": "",
                                    "arguments": "",
                                }
                            if tc.id:
                                collected_tool_calls[idx]["id"] = tc.id
                            if tc.function:
                                if tc.function.name:
                                    collected_tool_calls[idx]["name"] = tc.function.name
                                if tc.function.arguments:
                                    collected_tool_calls[idx][
                                        "arguments"
                                    ] += tc.function.arguments

                # Process any tool calls after streaming completes
                if collected_tool_calls:
                    # Add assistant message with tool calls to history
                    tool_calls_for_message = []
                    for tc_data in collected_tool_calls.values():
                        tool_calls_for_message.append(
                            {
                                "id": tc_data["id"],
                                "type": "function",
                                "function": {
                                    "name": tc_data["name"],
                                    "arguments": tc_data["arguments"],
                                },
                            }
                        )

                    messages.append(
                        {
                            "role": "assistant",
                            "content": current_content or None,
                            "tool_calls": tool_calls_for_message,
                        }
                    )

                    # Execute tools and add results
                    for tc_data in collected_tool_calls.values():
                        tool_name = tc_data["name"]
                        try:
                            tool_input = json.loads(tc_data["arguments"])
                        except json.JSONDecodeError:
                            tool_input = {}

                        tool_result = self._execute_mcp_tool(tool_name, tool_input)

                        tool_uses.append(
                            {
                                "name": tool_name,
                                "input": tool_input,
                                "result": tool_result,
                            }
                        )

                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_data["id"],
                                "content": tool_result,
                            }
                        )

                    # Make final call for response after tool execution
                    final_response = llm.completion(
                        messages=messages,
                        tools=tools,
                    )

                    final_content = final_response.choices[0].message.content or ""
                    current_content = final_content

            else:
                # Non-streaming: use tool calling loop
                tool_uses = []
                max_iterations = 10
                iteration = 0

                while iteration < max_iterations:
                    iteration += 1

                    response = llm.completion(
                        messages=messages,
                        tools=tools,
                    )

                    assistant_msg = response.choices[0].message

                    # Check for tool calls
                    if assistant_msg.tool_calls:
                        messages.append(assistant_msg.model_dump())

                        for tool_call in assistant_msg.tool_calls:
                            tool_name = tool_call.function.name
                            try:
                                tool_input = json.loads(tool_call.function.arguments)
                            except json.JSONDecodeError:
                                tool_input = {}

                            tool_result = self._execute_mcp_tool(tool_name, tool_input)

                            tool_uses.append(
                                {
                                    "name": tool_name,
                                    "input": tool_input,
                                    "result": tool_result,
                                }
                            )

                            messages.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "content": tool_result,
                                }
                            )

                        continue

                    # No more tool calls
                    break

                current_content = response.choices[0].message.content or ""

            # Update final message
            assistant_message.content = current_content
            assistant_message.metadata = {
                "streaming": False,
                "tool_uses": tool_uses,
                "model": llm.model_name,
            }
            assistant_message.save()

            return assistant_message

        except Exception as e:
            logger.error(f"AI response generation failed: {e}")
            # Create error message
            error_message = JobQuoteChat.objects.create(
                job=Job.objects.get(id=job_id),
                message_id=f"assistant-error-{uuid.uuid4()}",
                role="assistant",
                content=f"I apologize, but I encountered an error processing your request: {str(e)}",
                metadata={"error": True, "error_message": str(e)},
            )
            return error_message
