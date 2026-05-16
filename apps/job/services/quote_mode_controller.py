"""
Quote Mode Controller

Manages mode-based quote generation with structured JSON schemas and tool gating.
Provides CALC, PRICE, and TABLE modes for focused quoting operations.

Uses LiteLLM for provider-agnostic LLM access.
"""

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import jsonschema

from apps.job.models import Job
from apps.job.schemas import quote_mode_schemas
from apps.workflow.services.llm_service import LLMService

logger = logging.getLogger(__name__)


class QuoteModeController:
    """
    Controls mode-based quote generation with strict schema validation
    and tool gating to prevent premature operations.
    """

    MODES = ["CALC", "PRICE", "TABLE"]

    def __init__(self):
        """Initialize the controller with schemas and tool mappings."""
        self.schemas = {
            mode: quote_mode_schemas.get_schema(mode) for mode in self.MODES
        }
        self.tools = {
            mode: quote_mode_schemas.get_allowed_tools(mode) for mode in self.MODES
        }

    def get_system_prompt(self) -> str:
        """
        Get the minimal system prompt for mode-based operation.

        Returns:
            The system prompt string
        """
        return """You are a quoting helper. Process requests in the specified MODE.
- MODE=CALC: Calculate quantities and dimensions. For sheet materials, use calc_sheet_tenths tool. MUST call emit_calc_result with your final results.
- MODE=PRICE: Search for materials and pricing. MUST call emit_price_result with your final results.
- MODE=TABLE: Format quote tables. MUST call emit_table_result with your final results.

CRITICAL: You MUST call the appropriate emit_[mode]_result tool to submit your final answer.
The emit tool call should contain ALL required fields according to the schema.
Make reasonable assumptions and explicitly state them in the 'assumptions' field.
Avoid asking questions - use sensible defaults (e.g., 3mm thickness, 304 stainless, open-top boxes).
Never call tools from the wrong mode."""

    def _summarize_previous_context(
        self, chat_history: List[dict], gemini_client
    ) -> str:
        """
        Summarize previous conversation context for mode transitions.

        Args:
            chat_history: List of previous chat messages
            gemini_client: Gemini client for API calls

        Returns:
            Summary of relevant context from previous conversation
        """
        # Use a lightweight approach: extract assistant messages that contain results
        context_parts = []
        for msg in chat_history[-5:]:  # Last 5 messages
            if msg.get("role") == "model":
                # Extract text from parts
                for part in msg.get("parts", []):
                    if isinstance(part, str):
                        context_parts.append(part)

        if not context_parts:
            return ""

        # Join recent assistant responses as context
        return "\n\n".join(context_parts)

    def render_prompt(
        self,
        mode: str,
        user_input: str,
        job_ctx: Optional[Dict[str, Any]] = None,
        schema: Optional[Dict[str, Any]] = None,
        context_summary: Optional[str] = None,
    ) -> str:
        """
        Render a mode-specific prompt.

        Args:
            mode: The operation mode (CALC, PRICE, or TABLE)
            user_input: User's input text
            job_ctx: Optional job context information
            schema: Optional schema override
            context_summary: Optional summary of previous conversation

        Returns:
            The formatted prompt string
        """
        if schema is None:
            schema = self.schemas[mode]

        job_info = ""
        if job_ctx:
            job_info = f"\nJOB_CONTEXT: Job #{job_ctx.get('job_number', 'N/A')} for {job_ctx.get('client', 'N/A')}"

        context_info = ""
        if context_summary:
            context_info = f"\n\nPREVIOUS CONTEXT:\n{context_summary}\n\nUse this context to avoid re-asking the user for information already provided."

        mode_tasks = {
            "CALC": "Calculate required items from specifications. Call emit_calc_result with complete results including items list and assumptions.",
            "PRICE": "Search for materials using available tools, then call emit_price_result with normalized specs and pricing candidates.",
            "TABLE": "Format the quote data and call emit_table_result with rows, totals, and markdown table.",
        }

        return f"""MODE={mode}
SCHEMA for {mode}: {json.dumps(schema, indent=2)}{job_info}{context_info}
CURRENT INPUT: {user_input}
TASK: {mode_tasks[mode]}

IMPORTANT: You MUST call emit_{mode.lower()}_result with your complete results.
Consider the full conversation context when processing this input."""

    def validate_json(self, data: Any, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate JSON data against a schema.

        Args:
            data: The data to validate
            schema: The JSON schema

        Returns:
            The validated data

        Raises:
            jsonschema.ValidationError: If validation fails
        """
        try:
            jsonschema.validate(instance=data, schema=schema)
            return data
        except jsonschema.ValidationError as e:
            logger.error(f"Schema validation failed: {e}")
            raise

    def _proto_to_dict(self, obj: Any) -> Any:
        """
        Recursively convert protobuf/MapComposite objects to plain dicts.

        Args:
            obj: Object that might be a protobuf wrapper

        Returns:
            Plain Python object (dict, list, or primitive)
        """
        if obj is None:
            return None
        elif hasattr(obj, "__class__") and "MapComposite" in str(type(obj)):
            # This is a protobuf map wrapper - convert to dict
            result = {}
            for key in obj:
                result[key] = self._proto_to_dict(obj[key])
            return result
        elif hasattr(obj, "__class__") and "RepeatedComposite" in str(type(obj)):
            # This is a protobuf repeated wrapper - convert to list
            return [self._proto_to_dict(item) for item in obj]
        elif isinstance(obj, dict):
            return {k: self._proto_to_dict(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._proto_to_dict(item) for item in obj]
        else:
            # Primitive type or already converted
            return obj

    def _clean_schema_for_tools(self, schema: Dict[str, Any]) -> Dict[str, Any]:
        """
        Clean JSON Schema for use with LLM tool definitions.
        Keep only: type, description, properties, required, items, enum

        Args:
            schema: Original JSON schema

        Returns:
            Cleaned schema compatible with LLM tools
        """
        # Only these fields are safe for Gemini
        allowed_fields = {
            "type",
            "description",
            "properties",
            "required",
            "items",
            "enum",
        }

        def clean_dict(d: dict) -> dict:
            """Recursively clean dictionary keeping only allowed fields."""
            if not isinstance(d, dict):
                return d

            cleaned = {}
            for key, value in d.items():
                if key not in allowed_fields:
                    continue

                if key == "type":
                    # Handle nullable types - remove "null" from arrays
                    if isinstance(value, list):
                        non_null = [t for t in value if t != "null"]
                        cleaned[key] = non_null[0] if len(non_null) == 1 else non_null
                    else:
                        cleaned[key] = value

                elif key == "items":
                    # Gemini handles single-schema form best
                    if isinstance(value, list):
                        cleaned[key] = clean_dict(value[0]) if value else {}
                    else:
                        cleaned[key] = clean_dict(value)

                elif key == "properties":
                    cleaned[key] = {k: clean_dict(v) for k, v in value.items()}

                elif key == "enum":
                    # Limit enum size to prevent bloat (keep first 20)
                    cleaned[key] = value[:20] if len(value) > 20 else value

                elif isinstance(value, dict):
                    cleaned[key] = clean_dict(value)
                elif isinstance(value, list):
                    cleaned[key] = [
                        clean_dict(item) if isinstance(item, dict) else item
                        for item in value
                    ]
                else:
                    cleaned[key] = value

            return cleaned

        return clean_dict(schema)

    def get_mcp_tools_for_mode(self, mode: str) -> List[Dict[str, Any]]:
        """
        Get MCP tool definitions for a specific mode (OpenAI format for LiteLLM).

        Args:
            mode: The operation mode

        Returns:
            List of tool definitions in OpenAI format
        """
        allowed_tool_names = self.tools.get(mode, [])

        # Define all available tools in OpenAI format
        all_tools = {
            "calc_sheet_tenths": {
                "type": "function",
                "function": {
                    "name": "calc_sheet_tenths",
                    "description": "Calculate how many 'tenths' of a sheet a part occupies. Sheet divided into 5x2 grid (600x480mm sections for 1200x2400mm sheet). Returns number of sections needed.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "part_width_mm": {
                                "type": "number",
                                "description": "Width of part in mm",
                            },
                            "part_height_mm": {
                                "type": "number",
                                "description": "Height of part in mm",
                            },
                            "sheet_width_mm": {
                                "type": "number",
                                "description": "Sheet width in mm (default 1200)",
                            },
                            "sheet_height_mm": {
                                "type": "number",
                                "description": "Sheet height in mm (default 2400)",
                            },
                        },
                        "required": ["part_width_mm", "part_height_mm"],
                    },
                },
            },
            "search_products": {
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
            "get_pricing_for_material": {
                "type": "function",
                "function": {
                    "name": "get_pricing_for_material",
                    "description": "Get pricing information for specific materials",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "material_type": {
                                "type": "string",
                                "description": "Type of material (e.g., steel, aluminium)",
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
            "compare_suppliers": {
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
            # Emit tools for structured output
            "emit_calc_result": {
                "type": "function",
                "function": {
                    "name": "emit_calc_result",
                    "description": "Submit the final calculation results. Call this after calculating all required items.",
                    "parameters": self._clean_schema_for_tools(self.schemas["CALC"]),
                },
            },
            "emit_price_result": {
                "type": "function",
                "function": {
                    "name": "emit_price_result",
                    "description": "Submit the final pricing results. Call this after gathering all pricing information.",
                    "parameters": self._clean_schema_for_tools(self.schemas["PRICE"]),
                },
            },
            "emit_table_result": {
                "type": "function",
                "function": {
                    "name": "emit_table_result",
                    "description": "Submit the final formatted table. Call this after formatting the quote table.",
                    "parameters": self._clean_schema_for_tools(self.schemas["TABLE"]),
                },
            },
        }

        # Return only the tools allowed for this mode
        return [all_tools[name] for name in allowed_tool_names if name in all_tools]

    def infer_mode(self, user_input: str, current_mode: Optional[str] = None) -> str:
        """
        Use LLM to determine the mode based on user input and current mode.

        Args:
            user_input: The user's input text
            current_mode: Current mode if in a conversation (None for new conversation)

        Returns:
            The mode to use
        """
        # FAIL EARLY - current_mode must be valid if provided
        if current_mode and current_mode not in self.MODES:
            error_msg = (
                f"Invalid current_mode '{current_mode}', expected one of {self.MODES}"
            )
            exc = ValueError(error_msg)
            raise exc

        llm = LLMService()

        current_mode_text = (
            f"CURRENT MODE: {current_mode}"
            if current_mode
            else "CURRENT MODE: None (starting new conversation - default to CALC)"
        )

        prompt = f"""Classify what the user wants RIGHT NOW.

{current_mode_text}

USER MESSAGE: "{user_input}"

CLASSIFICATION:
- CALC: User wants calculations, dimensions, quantities, materials needed
- PRICE: User wants to know costs, prices, or supplier information
- TABLE: User wants a final summary/quote with totals

RULES:
- If user is answering a question or providing details, use CURRENT MODE
- If no current mode, use CALC
- Otherwise, classify based on what they're asking for

Reply with ONE WORD ONLY: CALC, PRICE, or TABLE"""

        try:
            response = llm.get_text_response(
                messages=[{"role": "user", "content": prompt}],
            )
            inferred_mode = response.strip().upper()

            # FAIL EARLY if invalid
            if inferred_mode not in self.MODES:
                error_msg = f"LLM returned invalid mode '{inferred_mode}', expected one of {self.MODES}"
                logger.error(error_msg)
                exc = ValueError(error_msg)
                raise exc

            logger.info(f"Mode decision: {current_mode} -> {inferred_mode}")
            return inferred_mode

        except Exception:
            raise

    def run(
        self,
        mode: str,
        user_input: str,
        job: Optional[Job] = None,
        llm_service: Optional[LLMService] = None,
        chat_history: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Execute a mode with the given input using LiteLLM.

        Args:
            mode: The operation mode (CALC, PRICE, or TABLE)
            user_input: User's input text
            job: Optional Job instance for context
            llm_service: Optional LLMService instance (creates one if not provided)
            chat_history: Optional list of previous messages in OpenAI format

        Returns:
            Tuple of (response_data, has_questions)

        Raises:
            ValueError: If mode is invalid
            jsonschema.ValidationError: If response doesn't match schema
        """
        if mode not in self.MODES:
            raise ValueError(f"Invalid mode: {mode}. Must be one of {self.MODES}")

        logger.info(f"Running mode {mode} with input: {user_input[:100]}...")

        # Prepare job context if available
        job_ctx = None
        if job:
            job_ctx = {
                "job_number": job.job_number,
                "client": job.client.name if job.client else "N/A",
                "description": job.description or "",
            }

        # Get schema and tools for this mode
        schema = self.schemas[mode]
        allowed_tools = self.get_mcp_tools_for_mode(mode)

        # Render the prompt
        prompt = self.render_prompt(mode, user_input, job_ctx, schema, None)

        # Create LLM service if not provided
        if llm_service is None:
            llm_service = LLMService()

        # Build message history for LiteLLM
        messages = []

        # Add system prompt
        messages.append({"role": "system", "content": self.get_system_prompt()})

        # Add chat history if provided (convert from Gemini format if needed)
        if chat_history:
            for msg in chat_history:
                role = msg.get("role", "user")
                # Convert Gemini 'model' role to 'assistant'
                if role == "model":
                    role = "assistant"
                # Extract text content from parts if present
                parts = msg.get("parts", [])
                if parts:
                    content = parts[0] if isinstance(parts[0], str) else str(parts[0])
                else:
                    content = msg.get("content", "")
                messages.append({"role": role, "content": content})

        # Add current user prompt
        messages.append({"role": "user", "content": prompt})

        # Process response to find emit tool call
        emit_tool_name = f"emit_{mode.lower()}_result"
        max_iterations = 10  # Prevent infinite loops
        iteration = 0

        while iteration < max_iterations:
            iteration += 1
            logger.debug(f"Processing response iteration {iteration}")

            try:
                response = llm_service.completion(
                    messages=messages,
                    tools=allowed_tools,
                )
            except Exception as e:
                logger.error(f"Error calling LLM: {e}")
                logger.error(f"Messages: {messages[-1]}")
                logger.error(f"Tools: {[t['function']['name'] for t in allowed_tools]}")
                raise

            # Get the assistant's message
            assistant_message = response.choices[0].message

            # Check if response contains tool calls
            if assistant_message.tool_calls:
                # Add assistant message to history
                messages.append(assistant_message.model_dump())

                # Collect all function calls from this turn
                emit_call = None
                intermediate_calls = []

                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        tool_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}
                    tool_call_id = tool_call.id

                    logger.info(f"Tool call detected: {tool_name}")

                    if tool_name == emit_tool_name:
                        emit_call = (tool_name, tool_args, tool_call_id)
                    else:
                        intermediate_calls.append((tool_name, tool_args, tool_call_id))

                # If emit tool was called, return its results
                if emit_call:
                    tool_name, tool_args, _ = emit_call
                    logger.info(f"Emit tool called: {tool_name}")
                    logger.debug(f"Emit tool args: {tool_args}")

                    # Validate against schema
                    validated_data = self.validate_json(tool_args, schema)

                    # Check for questions
                    questions = validated_data.get("questions", [])
                    has_questions = len(questions) > 0

                    if has_questions:
                        logger.info(
                            f"Mode {mode} has {len(questions)} clarifying questions"
                        )
                    else:
                        logger.info(
                            f"Mode {mode} completed successfully with no questions"
                        )

                    return validated_data, has_questions

                # Execute intermediate tools and add results to messages
                if intermediate_calls:
                    logger.info(
                        f"Executing {len(intermediate_calls)} intermediate tool(s)"
                    )

                    for tool_name, tool_args, tool_call_id in intermediate_calls:
                        logger.info(
                            f"Executing intermediate tool: {tool_name} with args: {tool_args}"
                        )
                        tool_result = self._execute_tool(tool_name, tool_args)

                        # Add tool result to messages
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call_id,
                                "content": str(tool_result),
                            }
                        )

                    continue

            # Check if there's text content (model might be explaining or asking)
            text_content = assistant_message.content
            if text_content:
                logger.debug(f"Model response text: {text_content[:200]}...")

                # Add assistant message to history
                messages.append({"role": "assistant", "content": text_content})

                # If we're here and no emit tool was called, prompt for it
                if iteration == 1:
                    logger.info(
                        f"No emit tool called yet, prompting for {emit_tool_name}"
                    )
                    messages.append(
                        {
                            "role": "user",
                            "content": f"Please complete your analysis and call the {emit_tool_name} tool with your final results.",
                        }
                    )
                else:
                    # Give model another chance
                    messages.append(
                        {
                            "role": "user",
                            "content": f"You must call {emit_tool_name} to submit your results. Please do so now.",
                        }
                    )

        # If we get here, something went wrong
        raise ValueError(
            f"Model did not call {emit_tool_name} after {max_iterations} attempts"
        )

    def _execute_tool(self, tool_name: str, arguments: dict) -> str:
        """
        Execute a tool and return its result.

        Args:
            tool_name: Name of the tool to execute
            arguments: Arguments to pass to the tool

        Returns:
            String result from the tool execution
        """
        # Import the quoting tools
        from apps.quoting.mcp import QuotingTool

        try:
            quoting_tool = QuotingTool()
            tool_map = {
                "calc_sheet_tenths": quoting_tool.calc_sheet_tenths,
                "search_products": quoting_tool.search_products,
                "get_pricing_for_material": quoting_tool.get_pricing_for_material,
                "compare_suppliers": quoting_tool.compare_suppliers,
            }

            if tool_name in tool_map:
                result = tool_map[tool_name](**arguments)
                logger.debug(
                    f"Tool {tool_name} returned: {result[:500] if isinstance(result, str) else result}..."
                )
                return result
            elif tool_name.startswith("emit_"):
                # Emit tools don't need execution, they're terminal
                logger.debug(f"Emit tool {tool_name} doesn't require execution")
                return None
            else:
                logger.warning(f"Unknown tool requested: {tool_name}")
                return f"Unknown tool: {tool_name}"
        except Exception as e:
            logger.error(f"Tool execution failed for {tool_name}: {e}")
            return f"Error executing tool '{tool_name}': {str(e)}"
