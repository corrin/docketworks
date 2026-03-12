"""
Chat Service (LiteLLM)

Handles AI-powered chat responses using LiteLLM for provider-agnostic access
and integrates with the application's internal tools (MCP - Model Context Protocol).

This service provides a seamless way to generate intelligent, context-aware
responses for quoting across multiple LLM providers.
"""

import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from django.db import transaction

from apps.job.models import Job, JobQuoteChat
from apps.job.services.chat_file_service import ChatFileService
from apps.job.services.quote_mode_controller import QuoteModeController
from apps.quoting.mcp import QuotingTool, SupplierProductQueryTool
from apps.workflow.models import CompanyDefaults
from apps.workflow.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class ChatService:
    """
    Service for handling AI chat responses using LiteLLM with tool integration.
    """

    def __init__(self) -> None:
        self.quoting_tool = QuotingTool()
        self.query_tool = SupplierProductQueryTool()
        self.mode_controller = QuoteModeController()
        self.file_service = ChatFileService()

    def start_conversation(self) -> None:
        """Initialize LLM service for this chat session."""
        # LLMService handles configuration automatically from AIProvider model
        self.llm = LLMService()
        logger.info(f"LLM configured for chat session: {self.llm.model_name}")

    def get_llm_service(self) -> LLMService:
        """Get a configured LLMService instance."""
        return LLMService()

    def _get_system_prompt(self, job: Job) -> str:
        """Generate system prompt with job context."""
        company = CompanyDefaults.get_solo()
        return f"""You are an intelligent quoting assistant for {company.company_name},
a custom metal fabrication business. Your role is to help estimators create accurate
quotes by using the available tools to find material pricing, compare suppliers,
and generate estimates.

Current Job Context:
- Job: {job.name} (#{job.job_number})
- Job ID: {job.id}
- Client: {job.client.name}
- Status: {job.get_status_display()}
- Description: {job.description or 'No description available'}

Always be helpful, professional, and specific in your responses. When providing
pricing or material recommendations, explain your reasoning and mention any relevant
supplier information. Use the tools provided to answer user queries about products,
pricing, and suppliers."""

    def _get_mcp_tools(self) -> List[Dict[str, Any]]:
        """Define MCP tools in OpenAI format for LiteLLM."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "search_products",
                    "description": "Search supplier products by description or specifications",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search term for products",
                            },
                            "supplier_name": {
                                "type": "string",
                                "description": "Optional supplier name to filter by",
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
                                "description": "Optional dimensions like '4x8'",
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
                    "description": "Create a quote estimate for a job, including materials and labor",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "job_id": {
                                "type": "string",
                                "description": "The UUID of the job to create the quote for",
                            },
                            "materials": {
                                "type": "string",
                                "description": "A description of the materials needed",
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
                    "description": "Get the status of supplier data scraping and price lists",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "supplier_name": {
                                "type": "string",
                                "description": "Optional supplier name to filter by",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "compare_suppliers",
                    "description": "Compare pricing across different suppliers for a specific material",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "material_query": {
                                "type": "string",
                                "description": "Material to compare prices for (e.g., 'steel angle')",
                            },
                        },
                        "required": ["material_query"],
                    },
                },
            },
        ]

    def _execute_mcp_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Execute an MCP tool by name and return its string output."""
        try:
            tool_map = {
                "search_products": self.quoting_tool.search_products,
                "get_pricing_for_material": self.quoting_tool.get_pricing_for_material,
                "create_quote_estimate": self.quoting_tool.create_quote_estimate,
                "get_supplier_status": self.quoting_tool.get_supplier_status,
                "compare_suppliers": self.quoting_tool.compare_suppliers,
            }
            if tool_name in tool_map:
                return tool_map[tool_name](**arguments)
            return f"Unknown tool: {tool_name}"
        except Exception as e:
            logger.error(f"MCP tool execution failed for {tool_name}: {e}")
            return f"Error executing tool '{tool_name}': {str(e)}"

    # ---------------------------------------------------------------------
    # Role Conversion Helpers
    # ---------------------------------------------------------------------

    @staticmethod
    def _to_openai_role(db_role: str) -> str:
        """
        Convert roles stored in the database to OpenAI format.

        Args:
            db_role: Role string from `JobQuoteChat.role`.

        Returns:
            A valid OpenAI role string.
        """
        return db_role  # 'user' and 'assistant' are already correct

    def _add_context_for_mode_transition(
        self, chat_history: List[Dict[str, Any]], current_mode: str
    ) -> List[Dict[str, Any]]:
        """
        Add a synthetic context message when transitioning to PRICE mode.

        This injects previous CALC results as a structured "CONTEXT" message
        so the model doesn't re-ask for information already provided.

        Args:
            chat_history: Current chat history
            current_mode: The mode being entered

        Returns:
            Enhanced chat history with context message if applicable
        """
        # Only add context when transitioning to PRICE mode
        if current_mode != "PRICE":
            return chat_history

        # Extract recent calculation results from assistant messages
        recent_context_parts = []
        for msg in chat_history[-6:]:  # Look at last 6 messages
            if msg.get("role") == "assistant":
                content = msg.get("content", "")
                if isinstance(content, str):
                    # Look for calculation results or material specifications
                    if any(
                        keyword in content.lower()
                        for keyword in [
                            "calculation",
                            "flat pattern",
                            "dimensions",
                            "thickness",
                            "material",
                            "quantity",
                        ]
                    ):
                        recent_context_parts.append(content)

        # If no relevant context found, don't inject anything
        if not recent_context_parts:
            return chat_history

        # Create a synthetic context message
        context_text = (
            "CONTEXT FROM PREVIOUS CONVERSATION:\n\n"
            + "\n\n".join(recent_context_parts)
            + "\n\n"
            "Use the above information to answer the pricing request. "
            "Do not re-ask for details already provided above."
        )

        context_msg = {"role": "user", "content": context_text}

        # Insert context message before the final user message
        enhanced = chat_history.copy()
        enhanced.append(context_msg)

        logger.info(f"Injected context message for {current_mode} mode transition")
        logger.debug(f"Context message preview: {context_text[:200]}...")

        return enhanced

    def _build_multimodal_content(
        self,
        text_content: str,
        message_files: List[Any],
        llm: LLMService,
    ) -> Any:
        """
        Build multimodal content for a message with file attachments.

        Args:
            text_content: The text content of the message
            message_files: List of JobFile instances attached to the message
            llm: LLMService instance to check for vision support

        Returns:
            Either a string (text only) or a list of content parts (multimodal)
        """
        if not message_files or not llm.supports_vision():
            # Fall back to text reference if no files or no vision support
            if message_files:
                file_names = [f.filename for f in message_files]
                return text_content + f"\n\n[Attached files: {', '.join(file_names)}]"
            return text_content

        # Build multimodal content parts
        content_parts = []

        for f in message_files:
            file_path = os.path.join(f.full_path, f.filename)
            if not os.path.exists(file_path):
                logger.warning(f"File not found for multimodal: {file_path}")
                content_parts.append(
                    {
                        "type": "text",
                        "text": f"[Attached file (not found): {f.filename}]",
                    }
                )
                continue

            mime_type = f.mime_type or ""

            if mime_type.startswith("image/"):
                # Create image content part
                try:
                    img_msg = LLMService.create_image_message(file_path, "")
                    # Extract just the image_url part (not the text part)
                    for part in img_msg["content"]:
                        if part["type"] == "image_url":
                            content_parts.append(part)
                            break
                    logger.info(f"Added image to multimodal content: {f.filename}")
                except Exception as e:
                    logger.error(f"Failed to load image {f.filename}: {e}")
                    content_parts.append(
                        {
                            "type": "text",
                            "text": f"[Image file (error loading): {f.filename}]",
                        }
                    )

            elif mime_type == "application/pdf":
                # Create PDF content part
                try:
                    pdf_msg = LLMService.create_pdf_message(file_path, "")
                    # Extract just the pdf/image_url part (not the text part)
                    for part in pdf_msg["content"]:
                        if part["type"] == "image_url":
                            content_parts.append(part)
                            break
                    logger.info(f"Added PDF to multimodal content: {f.filename}")
                except Exception as e:
                    logger.error(f"Failed to load PDF {f.filename}: {e}")
                    content_parts.append(
                        {
                            "type": "text",
                            "text": f"[PDF file (error loading): {f.filename}]",
                        }
                    )

            else:
                # Unsupported file type - just mention it
                content_parts.append(
                    {
                        "type": "text",
                        "text": f"[Attached file: {f.filename} ({mime_type})]",
                    }
                )

        # Add the text content last
        content_parts.append(
            {
                "type": "text",
                "text": text_content,
            }
        )

        return content_parts

    @transaction.atomic
    def generate_ai_response(
        self, job_id: str, user_message: str, mode: Optional[str] = None
    ) -> JobQuoteChat:
        """
        Generates an AI response using LiteLLM and MCP tools.

        Args:
            job_id: The UUID of the job
            user_message: The user's message
            mode: Optional mode (CALC, PRICE, TABLE) for mode-based operation

        Returns:
            JobQuoteChat instance with the AI response
        """
        logger.info(
            f"Starting AI response generation for job {job_id} with "
            f"message: {user_message}"
        )
        try:
            job = Job.objects.get(id=job_id)
            logger.debug(f"Retrieved job: {job.name} (#{job.job_number})")

            llm = self.get_llm_service()
            logger.info(f"LLM configured with model: {llm.model_name}")

            # -----------------------------------------------------------------
            # Initialise tool metadata tracking
            # -----------------------------------------------------------------
            tool_definitions = self._get_mcp_tools()
            tool_calls: List[Dict[str, Any]] = []

            system_prompt = self._get_system_prompt(job)
            logger.debug(f"System prompt set: {system_prompt}")

            # Build conversation history for the model
            messages = [{"role": "system", "content": system_prompt}]

            recent_messages = JobQuoteChat.objects.filter(job=job).order_by(
                "timestamp"
            )[:20]
            logger.debug(
                f"Retrieved {len(recent_messages)} recent messages for context"
            )

            history_for_metadata = []
            for msg in recent_messages:
                logger.debug(f"Adding to history: {msg.role} - {msg.content[:50]}...")
                history_for_metadata.append(
                    {
                        "role": self._to_openai_role(msg.role),
                        "content": msg.content,
                    }
                )
                messages.append(
                    {
                        "role": self._to_openai_role(msg.role),
                        "content": msg.content,
                    }
                )

            # Add the new user message
            messages.append({"role": "user", "content": user_message})
            logger.info(f"Sending message to LLM: {user_message}")

            # Process with tool calling loop
            max_iterations = 10
            iteration = 0

            while iteration < max_iterations:
                iteration += 1

                response = llm.completion(
                    messages=messages,
                    tools=tool_definitions,
                )

                assistant_message = response.choices[0].message

                # Check for tool calls
                if assistant_message.tool_calls:
                    # Add assistant message to history
                    messages.append(assistant_message.model_dump())

                    for tool_call in assistant_message.tool_calls:
                        tool_name = tool_call.function.name
                        try:
                            tool_args = json.loads(tool_call.function.arguments)
                        except json.JSONDecodeError:
                            tool_args = {}
                        tool_call_id = tool_call.id

                        logger.info(
                            f"Tool call: Executing {tool_name} with args: {tool_args}"
                        )
                        tool_result = self._execute_mcp_tool(tool_name, tool_args)
                        logger.debug(
                            f"Tool {tool_name} returned: {tool_result[:200]}..."
                        )

                        # Record the tool invocation for metadata
                        tool_calls.append(
                            {
                                "name": tool_name,
                                "arguments": tool_args,
                                "result_preview": tool_result[:200],
                            }
                        )

                        # Add tool result to messages
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "content": str(tool_result),
                            }
                        )

                    continue

                # No more tool calls - we have the final response
                break

            # The final response from the model
            final_content = assistant_message.content or ""
            logger.info(
                f"Final response from LLM (length: {len(final_content)}): "
                f"{final_content[:100]}..."
            )

            # Persist the assistant's final message
            logger.debug("Saving assistant message to database")
            saved_message = JobQuoteChat.objects.create(
                job=job,
                message_id=f"assistant-{uuid.uuid4()}",
                role="assistant",
                content=final_content,
                metadata={
                    "model": llm.model_name,
                    "system_prompt": system_prompt,
                    "user_message": user_message,
                    "chat_history": history_for_metadata,
                    "tool_definitions": tool_definitions,
                    "tool_calls": tool_calls,
                },
            )
            logger.info(
                f"Successfully generated AI response for job {job_id}. "
                f"Message ID: {saved_message.message_id}"
            )
            return saved_message

        except Exception as e:
            logger.exception(f"AI response generation failed for job {job_id}: {e}")
            # Create and return an error message to be displayed in the chat
            error_message = JobQuoteChat.objects.create(
                job=Job.objects.get(id=job_id),
                message_id=f"assistant-error-{uuid.uuid4()}",
                role="assistant",
                content=(
                    f"I apologize, but I encountered an error processing your "
                    f"request: {str(e)}"
                ),
                metadata={"error": True, "error_message": str(e)},
            )
            return error_message

    @transaction.atomic
    def generate_mode_response(
        self, job_id: str, user_message: str, mode: Optional[str] = None
    ) -> JobQuoteChat:
        """
        Generate a response using the mode-based system.

        Args:
            job_id: The UUID of the job
            user_message: The user's message
            mode: Optional mode override. If None, mode is inferred from input

        Returns:
            JobQuoteChat instance with the structured response
        """
        logger.info(f"Starting mode-based response for job {job_id}")

        try:
            job = Job.objects.get(id=job_id)
            llm = self.get_llm_service()

            # Build conversation history from database
            chat_history = []
            recent_messages = JobQuoteChat.objects.filter(job=job).order_by(
                "timestamp"
            )[:20]
            logger.debug(
                f"Retrieved {len(recent_messages)} recent messages for context"
            )

            # Extract all file IDs from chat history
            all_file_ids = self.file_service.extract_file_ids_from_chat_history(
                list(recent_messages)
            )

            # Fetch job files if there are any file references
            job_files_dict = {}
            if all_file_ids:
                job_files = self.file_service.fetch_job_files(job_id, all_file_ids)
                logger.info(f"Found {len(job_files)} files attached to conversation")
                job_files_dict = {str(f.id): f for f in job_files}

            for msg in recent_messages:
                logger.debug(f"Adding to history: {msg.role} - {msg.content[:50]}...")

                # Build content - start with text
                content = msg.content
                role = self._to_openai_role(msg.role)

                # Handle file attachments with multimodal support
                if msg.metadata and "file_ids" in msg.metadata:
                    message_file_ids = msg.metadata["file_ids"]
                    message_files = [
                        job_files_dict[fid]
                        for fid in message_file_ids
                        if fid in job_files_dict
                    ]
                    if message_files:
                        # Build multimodal content if supported
                        content = self._build_multimodal_content(
                            content, message_files, llm
                        )

                chat_history.append(
                    {
                        "role": role,
                        "content": content,
                    }
                )

            # Infer mode if not provided
            if mode is None:
                # Get current mode from last assistant message
                current_mode = None
                for msg in reversed(list(recent_messages)):
                    if msg.role == "assistant" and msg.metadata:
                        current_mode = msg.metadata.get("mode")
                        if current_mode:
                            break

                mode = self.mode_controller.infer_mode(user_message, current_mode)
                logger.info(f"Inferred mode: {mode} (previous: {current_mode})")
            else:
                logger.info(f"Using explicit mode: {mode}")

            # Inject context summary as a message if switching modes
            enhanced_history = self._add_context_for_mode_transition(chat_history, mode)

            # Run the mode controller with enhanced chat history
            response_data, has_questions = self.mode_controller.run(
                mode=mode,
                user_input=user_message,
                job=job,
                llm_service=llm,
                chat_history=enhanced_history,
            )

            # Format the response for display
            if has_questions:
                # Format questions as a bulleted list
                questions = response_data.get("questions", [])
                content = "I need some clarification:\n\n"
                for q in questions:
                    content += f"* {q}\n"
            else:
                # Format the results based on mode
                if mode == "CALC":
                    results = response_data.get("results", {})
                    content = "**Calculation Results:**\n\n"
                    for key, value in results.items():
                        label = key.replace("_", " ").title()
                        if isinstance(value, float):
                            content += f"* {label}: {value:.2f}\n"
                        else:
                            content += f"* {label}: {value}\n"

                elif mode == "PRICE":
                    candidates = response_data.get("candidates", [])
                    content = "**Material Options:**\n\n"
                    for i, candidate in enumerate(candidates, 1):
                        content += f"**Option {i}: {candidate['supplier']}**\n"
                        content += f"* SKU: {candidate['sku']}\n"
                        content += f"* Price: ${candidate['price_per_uom']:.2f}/{candidate['uom']}\n"
                        if candidate.get("lead_time_days"):
                            content += (
                                f"* Lead Time: {candidate['lead_time_days']} days\n"
                            )
                        if candidate.get("delivery"):
                            content += f"* Delivery: ${candidate['delivery']:.2f}\n"
                        if candidate.get("notes"):
                            content += f"* Notes: {candidate['notes']}\n"
                        content += "\n"

                elif mode == "TABLE":
                    markdown = response_data.get("markdown", "")
                    totals = response_data.get("totals", {})
                    content = markdown
                    if not content:
                        content = "**Quote Summary:**\n\n"
                        content += f"* Material: ${totals.get('material', 0):.2f}\n"
                        content += f"* Labour: ${totals.get('labour', 0):.2f}\n"
                        content += f"* Freight: ${totals.get('freight', 0):.2f}\n"
                        content += f"* Overheads: ${totals.get('overheads', 0):.2f}\n"
                        content += f"* Markup: {totals.get('markup_pct', 0)}%\n"
                        content += f"* **Total (ex GST): ${totals.get('grand_total_ex_gst', 0):.2f}**\n"

            # Save the response
            assistant_message = JobQuoteChat.objects.create(
                job=job,
                message_id=f"assistant-{uuid.uuid4()}",
                role="assistant",
                content=content,
                metadata={
                    "mode": mode,
                    "response_data": response_data,
                    "has_questions": has_questions,
                    "model": llm.model_name,
                    "user_message": user_message,
                },
            )

            logger.info(f"Successfully generated mode-based response for job {job_id}")
            return assistant_message

        except Exception as e:
            logger.exception(f"Mode-based response generation failed: {e}")
            # Create error message
            error_message = JobQuoteChat.objects.create(
                job=Job.objects.get(id=job_id),
                message_id=f"assistant-error-{uuid.uuid4()}",
                role="assistant",
                content=f"I encountered an error processing your request: {str(e)}",
                metadata={"error": True, "error_message": str(e), "mode": mode},
            )
            return error_message


# Backwards compatibility alias
GeminiChatService = ChatService
