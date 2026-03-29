"""
Comprehensive unit tests for ChatService

Tests cover:
- Service initialization and configuration
- AI response generation using LLMService
- Tool integration and execution
- Error handling and edge cases
- Message persistence and metadata
- Multimodal content handling
"""

import json
import os
import tempfile
import uuid
from unittest.mock import Mock, patch

from django.test import TestCase

from apps.client.models import Client
from apps.job.models import Job, JobQuoteChat
from apps.job.services.chat_service import ChatService
from apps.testing import BaseTestCase
from apps.workflow.enums import AIProviderTypes
from apps.workflow.models import AIProvider, CompanyDefaults, XeroPayItem


class MockLLMResponseBuilder:
    """
    Helper class to create realistic mock LLM responses.

    Based on actual LiteLLM response structure captured from real API calls:
    - ModelResponse with choices[0].message
    - message.content: str or None
    - message.tool_calls: None or List[ChatCompletionMessageToolCall]
    - message.role: "assistant"
    """

    @staticmethod
    def create_text_response(content: str) -> Mock:
        """Create a mock response with text content (no tool calls)."""
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = Mock()
        mock_response.choices[0].message.content = content
        mock_response.choices[0].message.tool_calls = None
        mock_response.choices[0].message.role = "assistant"
        # Add model_dump for serialization
        mock_response.choices[0].message.model_dump.return_value = {
            "content": content,
            "role": "assistant",
            "tool_calls": None,
            "function_call": None,
        }
        return mock_response

    @staticmethod
    def create_tool_call_response(
        tool_name: str, arguments: dict, tool_call_id: str = None
    ) -> Mock:
        """
        Create a mock response with a tool call.

        Note: In real LLM responses, arguments is a JSON string, not a dict.
        """
        if tool_call_id is None:
            tool_call_id = f"toolu_{uuid.uuid4().hex[:24]}"

        # Create the tool call object
        mock_function = Mock()
        mock_function.name = tool_name
        mock_function.arguments = json.dumps(arguments)  # JSON string, not dict!

        mock_tool_call = Mock()
        mock_tool_call.id = tool_call_id
        mock_tool_call.type = "function"
        mock_tool_call.function = mock_function

        # Create the response
        mock_response = Mock()
        mock_response.choices = [Mock()]
        mock_response.choices[0].message = Mock()
        mock_response.choices[0].message.content = (
            None  # No content when tool is called
        )
        mock_response.choices[0].message.tool_calls = [mock_tool_call]
        mock_response.choices[0].message.role = "assistant"
        # Add model_dump for serialization
        mock_response.choices[0].message.model_dump.return_value = {
            "content": None,
            "role": "assistant",
            "tool_calls": [
                {
                    "id": tool_call_id,
                    "type": "function",
                    "function": {
                        "name": tool_name,
                        "arguments": json.dumps(arguments),
                    },
                }
            ],
            "function_call": None,
        }
        return mock_response

    @staticmethod
    def create_mock_llm(model_name: str = "test-model") -> Mock:
        """Create a mock LLMService instance."""
        mock_llm = Mock()
        mock_llm.model_name = model_name
        mock_llm.supports_vision.return_value = False
        mock_llm.supports_tools.return_value = True
        return mock_llm


class ChatServiceConfigurationTests(BaseTestCase):
    """Test service configuration and initialization"""

    def setUp(self):
        """Set up test data"""
        self.company_defaults = CompanyDefaults.get_solo()

        self.client = Client.objects.create(
            name="Test Client",
            email="client@example.com",
            phone="0123456789",
            xero_last_modified="2024-01-01T00:00:00Z",
        )

        # Get Ordinary Time pay item (created by migration)
        self.xero_pay_item = XeroPayItem.get_ordinary_time()

        self.job = Job.objects.create(
            name="Test Job",
            job_number=1001,
            description="Test job description",
            client=self.client,
            status="quoting",
            default_xero_pay_item=self.xero_pay_item,
        )

        self.service = ChatService()

    def test_service_initialization(self):
        """Test service initializes with required components"""
        self.assertIsNotNone(self.service.quoting_tool)
        self.assertIsNotNone(self.service.query_tool)
        self.assertIsNotNone(self.service.mode_controller)
        self.assertIsNotNone(self.service.file_service)

    def test_get_llm_service_no_provider(self):
        """Test LLM service creation fails when no AI provider configured"""
        # Remove all AI providers
        AIProvider.objects.all().delete()

        with self.assertRaises(ValueError) as context:
            self.service.get_llm_service()

        self.assertIn("No AI provider configured", str(context.exception))

    def test_get_llm_service_no_api_key(self):
        """Test LLM service creation fails when provider has no API key"""
        AIProvider.objects.all().delete()
        AIProvider.objects.create(
            provider_type=AIProviderTypes.GOOGLE,
            default=True,
            model_name="gemini-pro",
            # No api_key set
        )

        with self.assertRaises(ValueError) as context:
            self.service.get_llm_service()

        self.assertIn("missing an API key", str(context.exception))

    def test_get_llm_service_no_model_name(self):
        """Test LLM service creation fails when provider has no model name"""
        AIProvider.objects.all().delete()
        AIProvider.objects.create(
            provider_type=AIProviderTypes.GOOGLE,
            default=True,
            api_key="test-key",
            # No model_name set
        )

        with self.assertRaises(ValueError) as context:
            self.service.get_llm_service()

        self.assertIn("missing a model name", str(context.exception))

    def test_system_prompt_generation(self):
        """Test system prompt includes job context"""
        prompt = self.service._get_system_prompt(self.job)

        self.assertIn(self.company_defaults.company_name, prompt)
        self.assertIn(self.job.name, prompt)
        self.assertIn(str(self.job.job_number), prompt)
        self.assertIn(self.client.name, prompt)
        self.assertIn(self.job.description, prompt)

    def test_mcp_tools_definition(self):
        """Test MCP tools are properly defined in OpenAI format"""
        tools = self.service._get_mcp_tools()

        self.assertIsInstance(tools, list)
        self.assertGreater(len(tools), 0)

        # Tools should be in OpenAI format (dicts with type: function)
        for tool in tools:
            self.assertIsInstance(tool, dict)
            self.assertEqual(tool["type"], "function")
            self.assertIn("function", tool)
            self.assertIn("name", tool["function"])
            self.assertIn("description", tool["function"])
            self.assertIn("parameters", tool["function"])

        tool_names = [tool["function"]["name"] for tool in tools]
        expected_tools = [
            "search_products",
            "get_pricing_for_material",
            "create_quote_estimate",
            "get_supplier_status",
            "compare_suppliers",
        ]

        for expected_tool in expected_tools:
            self.assertIn(expected_tool, tool_names)

    def test_role_conversion(self):
        """Test database role to OpenAI role conversion"""
        # Both 'user' and 'assistant' should map to themselves
        self.assertEqual(ChatService._to_openai_role("user"), "user")
        self.assertEqual(ChatService._to_openai_role("assistant"), "assistant")


class ChatServiceToolExecutionTests(TestCase):
    """Test MCP tool execution"""

    def setUp(self):
        self.service = ChatService()
        # Create a mock for the quoting_tool instance attribute
        self.mock_quoting_tool = Mock()
        self.service.quoting_tool = self.mock_quoting_tool

    def test_execute_unknown_tool(self):
        """Test execution of unknown tool"""
        result = self.service._execute_mcp_tool("unknown_tool", {})
        self.assertEqual(result, "Unknown tool: unknown_tool")

    def test_execute_tool_with_exception(self):
        """Test tool execution with exception"""
        self.mock_quoting_tool.search_products.side_effect = Exception("Tool error")

        result = self.service._execute_mcp_tool("search_products", {"query": "test"})

        self.assertIn("Error executing tool", result)
        self.assertIn("Tool error", result)


class ChatServiceResponseGenerationTests(BaseTestCase):
    """Test AI response generation with database transactions"""

    def setUp(self):
        """Set up test data"""
        self.company_defaults = CompanyDefaults.get_solo()

        self.client = Client.objects.create(
            name="Test Client",
            email="client@example.com",
            phone="0123456789",
            xero_last_modified="2024-01-01T00:00:00Z",
        )

        # Get Ordinary Time pay item (created by migration)
        self.xero_pay_item = XeroPayItem.get_ordinary_time()

        self.job = Job.objects.create(
            name="Test Job",
            job_number=1001,
            description="Test job description",
            client=self.client,
            status="quoting",
            default_xero_pay_item=self.xero_pay_item,
        )

        self.ai_provider = AIProvider.objects.create(
            provider_type=AIProviderTypes.GOOGLE,
            default=True,
            api_key="test-key",
            model_name="gemini-pro",
        )

        self.service = ChatService()

    def test_job_not_found(self):
        """Test response generation with non-existent job"""
        non_existent_job_id = str(uuid.uuid4())

        with self.assertRaises(Job.DoesNotExist):
            self.service.generate_ai_response(non_existent_job_id, "Test message")

    @patch.object(ChatService, "get_llm_service")
    def test_generate_response_simple(self, mock_get_llm):
        """Test simple response generation without tool calls"""
        mock_llm = MockLLMResponseBuilder.create_mock_llm("gemini-pro")
        mock_response = MockLLMResponseBuilder.create_text_response(
            "This is a test response"
        )
        mock_llm.completion.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = self.service.generate_ai_response(str(self.job.id), "Test message")

        self.assertIsInstance(result, JobQuoteChat)
        self.assertEqual(result.job, self.job)
        self.assertEqual(result.role, "assistant")
        self.assertEqual(result.content, "This is a test response")
        self.assertIn("model", result.metadata)
        self.assertIn("user_message", result.metadata)

    @patch.object(ChatService, "get_llm_service")
    def test_generate_response_with_tool_calls(self, mock_get_llm):
        """Test response generation with tool calls"""
        mock_llm = MockLLMResponseBuilder.create_mock_llm("gemini-pro")

        # First response triggers tool call
        tool_call_response = MockLLMResponseBuilder.create_tool_call_response(
            "search_products", {"query": "steel"}, "toolu_test123"
        )

        # Second response is the final text response
        final_response = MockLLMResponseBuilder.create_text_response(
            "Based on the search results, here are some steel options..."
        )

        mock_llm.completion.side_effect = [tool_call_response, final_response]
        mock_get_llm.return_value = mock_llm

        # Mock tool execution
        with patch.object(
            self.service, "_execute_mcp_tool", return_value="Tool result"
        ):
            result = self.service.generate_ai_response(
                str(self.job.id), "Find steel products"
            )

            self.assertIsInstance(result, JobQuoteChat)
            self.assertEqual(result.role, "assistant")
            self.assertIn("tool_calls", result.metadata)
            self.assertEqual(len(result.metadata["tool_calls"]), 1)
            self.assertEqual(
                result.metadata["tool_calls"][0]["name"], "search_products"
            )

    @patch.object(ChatService, "get_llm_service")
    def test_generate_response_with_history(self, mock_get_llm):
        """Test response generation includes conversation history"""
        # Create some existing chat messages
        JobQuoteChat.objects.create(
            job=self.job,
            message_id="user-1",
            role="user",
            content="Previous user message",
        )
        JobQuoteChat.objects.create(
            job=self.job,
            message_id="assistant-1",
            role="assistant",
            content="Previous assistant response",
        )

        mock_llm = MockLLMResponseBuilder.create_mock_llm("gemini-pro")
        mock_response = MockLLMResponseBuilder.create_text_response(
            "Response with history context"
        )
        mock_llm.completion.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        result = self.service.generate_ai_response(str(self.job.id), "New message")

        # Verify completion was called
        mock_llm.completion.assert_called_once()

        # Verify messages passed to completion include history
        call_kwargs = mock_llm.completion.call_args[1]
        messages = call_kwargs["messages"]

        # Should have: system prompt + 2 history messages + new user message
        self.assertEqual(len(messages), 4)

        # Verify response includes history in metadata
        self.assertIn("chat_history", result.metadata)
        self.assertEqual(len(result.metadata["chat_history"]), 2)

    @patch.object(ChatService, "get_llm_service")
    def test_generate_response_error_handling(self, mock_get_llm):
        """Test error handling in response generation"""
        # Mock the LLM service to raise an exception
        mock_get_llm.side_effect = Exception("API Error")

        result = self.service.generate_ai_response(str(self.job.id), "Test message")

        self.assertIsInstance(result, JobQuoteChat)
        self.assertEqual(result.role, "assistant")
        self.assertIn("error", result.content.lower())
        self.assertIn("API Error", result.content)
        self.assertTrue(result.metadata.get("error", False))


class ChatServiceMultimodalTests(BaseTestCase):
    """Test multimodal content handling"""

    def setUp(self):
        """Set up test data"""
        self.company_defaults = CompanyDefaults.get_solo()

        self.client = Client.objects.create(
            name="Test Client",
            email="client@example.com",
            phone="0123456789",
            xero_last_modified="2024-01-01T00:00:00Z",
        )

        self.xero_pay_item = XeroPayItem.get_ordinary_time()

        self.job = Job.objects.create(
            name="Test Job",
            job_number=1001,
            description="Test job description",
            client=self.client,
            status="quoting",
            default_xero_pay_item=self.xero_pay_item,
        )

        self.service = ChatService()

    def test_build_multimodal_content_no_files(self):
        """Test _build_multimodal_content returns text when no files"""
        mock_llm = MockLLMResponseBuilder.create_mock_llm()
        mock_llm.supports_vision.return_value = True

        result = self.service._build_multimodal_content("Test message", [], mock_llm)

        self.assertEqual(result, "Test message")

    def test_build_multimodal_content_no_vision_support(self):
        """Test _build_multimodal_content falls back to text reference"""
        mock_llm = MockLLMResponseBuilder.create_mock_llm()
        mock_llm.supports_vision.return_value = False

        # Create mock file
        mock_file = Mock()
        mock_file.filename = "test.png"

        result = self.service._build_multimodal_content(
            "Test message", [mock_file], mock_llm
        )

        self.assertIn("Test message", result)
        self.assertIn("[Attached files: test.png]", result)

    def test_build_multimodal_content_file_not_found(self):
        """Test _build_multimodal_content handles missing files"""
        mock_llm = MockLLMResponseBuilder.create_mock_llm()
        mock_llm.supports_vision.return_value = True

        # Create mock file with non-existent path
        mock_file = Mock()
        mock_file.filename = "missing.png"
        mock_file.full_path = "/nonexistent/path"
        mock_file.mime_type = "image/png"

        result = self.service._build_multimodal_content(
            "Test message", [mock_file], mock_llm
        )

        # Should return a list with text parts indicating file not found
        self.assertIsInstance(result, list)
        text_parts = [p for p in result if p["type"] == "text"]
        text_content = " ".join(p["text"] for p in text_parts)
        self.assertIn("not found", text_content)

    def test_build_multimodal_content_with_image(self):
        """Test _build_multimodal_content with image file"""
        mock_llm = MockLLMResponseBuilder.create_mock_llm()
        mock_llm.supports_vision.return_value = True

        # Create a temporary image file
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            # Write a minimal PNG file (1x1 transparent pixel)
            png_data = bytes(
                [
                    0x89,
                    0x50,
                    0x4E,
                    0x47,
                    0x0D,
                    0x0A,
                    0x1A,
                    0x0A,  # PNG signature
                    0x00,
                    0x00,
                    0x00,
                    0x0D,
                    0x49,
                    0x48,
                    0x44,
                    0x52,  # IHDR chunk
                    0x00,
                    0x00,
                    0x00,
                    0x01,
                    0x00,
                    0x00,
                    0x00,
                    0x01,
                    0x08,
                    0x06,
                    0x00,
                    0x00,
                    0x00,
                    0x1F,
                    0x15,
                    0xC4,
                    0x89,
                    0x00,
                    0x00,
                    0x00,
                    0x0A,
                    0x49,
                    0x44,
                    0x41,  # IDAT chunk
                    0x54,
                    0x78,
                    0x9C,
                    0x63,
                    0x00,
                    0x01,
                    0x00,
                    0x00,
                    0x05,
                    0x00,
                    0x01,
                    0x0D,
                    0x0A,
                    0x2D,
                    0xB4,
                    0x00,
                    0x00,
                    0x00,
                    0x00,
                    0x49,
                    0x45,
                    0x4E,
                    0x44,
                    0xAE,  # IEND chunk
                    0x42,
                    0x60,
                    0x82,
                ]
            )
            f.write(png_data)
            temp_path = f.name

        try:
            # Create mock file pointing to temp file
            mock_file = Mock()
            mock_file.filename = os.path.basename(temp_path)
            mock_file.full_path = os.path.dirname(temp_path)
            mock_file.mime_type = "image/png"

            result = self.service._build_multimodal_content(
                "Test message", [mock_file], mock_llm
            )

            # Should return a list with image and text parts
            self.assertIsInstance(result, list)
            types = [p["type"] for p in result]
            self.assertIn("image_url", types)
            self.assertIn("text", types)

        finally:
            os.unlink(temp_path)

    def test_build_multimodal_content_unsupported_file_type(self):
        """Test _build_multimodal_content with unsupported file type"""
        mock_llm = MockLLMResponseBuilder.create_mock_llm()
        mock_llm.supports_vision.return_value = True

        # Create mock file with unsupported type
        mock_file = Mock()
        mock_file.filename = "data.csv"
        mock_file.full_path = "/some/path"
        mock_file.mime_type = "text/csv"

        # Mock os.path.exists to return True
        with patch("os.path.exists", return_value=True):
            result = self.service._build_multimodal_content(
                "Test message", [mock_file], mock_llm
            )

        # Should return a list with text parts mentioning the attachment
        self.assertIsInstance(result, list)
        text_parts = [p for p in result if p["type"] == "text"]
        text_content = " ".join(p["text"] for p in text_parts)
        self.assertIn("data.csv", text_content)


class ChatServiceIntegrationTests(BaseTestCase):
    """Integration tests for the complete chat flow"""

    def setUp(self):
        """Set up test data"""
        self.company_defaults = CompanyDefaults.get_solo()

        self.client = Client.objects.create(
            name="Test Client",
            email="client@example.com",
            phone="0123456789",
            xero_last_modified="2024-01-01T00:00:00Z",
        )

        # Get Ordinary Time pay item (created by migration)
        self.xero_pay_item = XeroPayItem.get_ordinary_time()

        self.job = Job.objects.create(
            name="Test Job",
            job_number=1001,
            description="Test job description",
            client=self.client,
            status="quoting",
            default_xero_pay_item=self.xero_pay_item,
        )

        self.ai_provider = AIProvider.objects.create(
            provider_type=AIProviderTypes.GOOGLE,
            default=True,
            api_key="test-key",
            model_name="gemini-pro",
        )

    @patch.object(ChatService, "get_llm_service")
    def test_complete_chat_flow(self, mock_get_llm):
        """Test complete chat flow from user message to saved response"""
        service = ChatService()

        mock_llm = MockLLMResponseBuilder.create_mock_llm("gemini-pro")
        mock_response = MockLLMResponseBuilder.create_text_response(
            "Complete chat flow response"
        )
        mock_llm.completion.return_value = mock_response
        mock_get_llm.return_value = mock_llm

        # Execute the flow
        result = service.generate_ai_response(str(self.job.id), "Test complete flow")

        # Verify response
        self.assertIsInstance(result, JobQuoteChat)
        self.assertEqual(result.job, self.job)
        self.assertEqual(result.role, "assistant")
        self.assertEqual(result.content, "Complete chat flow response")

        # Verify message was saved to database
        saved_message = JobQuoteChat.objects.get(id=result.id)
        self.assertEqual(saved_message.content, "Complete chat flow response")
        self.assertIn("model", saved_message.metadata)
        self.assertIn("user_message", saved_message.metadata)
        self.assertIn("tool_definitions", saved_message.metadata)

    def test_conversation_persistence(self):
        """Test that conversation history is properly maintained"""
        # Create a sequence of messages
        messages = [
            ("user", "Hello"),
            ("assistant", "Hi there!"),
            ("user", "What can you help with?"),
            ("assistant", "I can help with quoting and materials"),
        ]

        for role, content in messages:
            JobQuoteChat.objects.create(
                job=self.job,
                message_id=f"{role}-{uuid.uuid4()}",
                role=role,
                content=content,
            )

        # Verify messages are retrievable in order
        history = JobQuoteChat.objects.filter(job=self.job).order_by("timestamp")
        self.assertEqual(history.count(), 4)

        for i, msg in enumerate(history):
            self.assertEqual(msg.role, messages[i][0])
            self.assertEqual(msg.content, messages[i][1])


class ChatServiceModeResponseTests(BaseTestCase):
    """Test mode-based response generation"""

    def setUp(self):
        """Set up test data"""
        self.company_defaults = CompanyDefaults.get_solo()

        self.client = Client.objects.create(
            name="Test Client",
            email="client@example.com",
            phone="0123456789",
            xero_last_modified="2024-01-01T00:00:00Z",
        )

        self.xero_pay_item = XeroPayItem.get_ordinary_time()

        self.job = Job.objects.create(
            name="Test Job",
            job_number=1001,
            description="Test job description",
            client=self.client,
            status="quoting",
            default_xero_pay_item=self.xero_pay_item,
        )

        self.ai_provider = AIProvider.objects.create(
            provider_type=AIProviderTypes.GOOGLE,
            default=True,
            api_key="test-key",
            model_name="gemini-pro",
        )

        self.service = ChatService()

    @patch.object(ChatService, "get_llm_service")
    def test_generate_mode_response_error_handling(self, mock_get_llm):
        """Test error handling in mode response generation"""
        mock_get_llm.side_effect = Exception("Mode Error")

        result = self.service.generate_mode_response(str(self.job.id), "Test message")

        self.assertIsInstance(result, JobQuoteChat)
        self.assertEqual(result.role, "assistant")
        self.assertIn("error", result.content.lower())
        self.assertTrue(result.metadata.get("error", False))
