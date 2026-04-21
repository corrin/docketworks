"""
Tests for chat database query optimization and bulk operations.
"""

from unittest.mock import Mock, patch

from apps.client.models import Client
from apps.job.models import Job, JobQuoteChat
from apps.job.services.chat_service import ChatService
from apps.testing import BaseTestCase
from apps.workflow.enums import AIProviderTypes
from apps.workflow.models import AIProvider, CompanyDefaults, XeroPayItem


def create_mock_llm(model_name: str = "test-model") -> Mock:
    """Create a mock LLMService instance."""
    mock_llm = Mock()
    mock_llm.model_name = model_name
    mock_llm.supports_vision.return_value = False
    mock_llm.supports_tools.return_value = True
    return mock_llm


def create_text_response(content: str) -> Mock:
    """Create a mock LLM response with text content (no tool calls)."""
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].message = Mock()
    mock_response.choices[0].message.content = content
    mock_response.choices[0].message.tool_calls = None
    mock_response.choices[0].message.role = "assistant"
    mock_response.choices[0].message.model_dump.return_value = {
        "content": content,
        "role": "assistant",
        "tool_calls": None,
        "function_call": None,
    }
    return mock_response


class ChatQueryOptimizationTests(BaseTestCase):
    """Test chat database query counts and bulk operations"""

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
            staff=self.test_staff,
        )

        self.ai_provider = AIProvider.objects.create(
            provider_type=AIProviderTypes.GOOGLE,
            default=True,
            api_key="test-key",
            model_name="gemini-pro",
        )

        self.service = ChatService()

    def test_database_query_optimization(self):
        """Test database query optimization"""
        # Create conversation history
        for i in range(50):
            role = "user" if i % 2 == 0 else "assistant"
            JobQuoteChat.objects.create(
                job=self.job,
                message_id=f"opt-msg-{i}",
                role=role,
                content=f"Optimization test message {i}",
            )

        # Monitor database queries
        with patch.object(self.service, "get_llm_service") as mock_get_llm:
            mock_llm = create_mock_llm("gemini-pro")
            mock_response = create_text_response("Optimized response")
            mock_llm.completion.return_value = mock_response
            mock_get_llm.return_value = mock_llm

            with self.assertNumQueries(
                7
            ):  # Job, CompanyDefaults, Client, History, Insert, Savepoint x2
                result = self.service.generate_ai_response(
                    str(self.job.id), "Test message"
                )
                self.assertIsNotNone(result)

    def test_bulk_message_creation(self):
        """Test bulk database message creation"""
        jobs = []
        for i in range(3):
            job = Job.objects.create(
                name=f"DB Test Job {i}",
                job_number=3000 + i,
                description=f"Database test job {i}",
                client=self.client,
                status="quoting",
                default_xero_pay_item=self.xero_pay_item,
                staff=self.test_staff,
            )
            jobs.append(job)

        # Create messages for each job
        for job in jobs:
            messages = []
            for i in range(20):
                role = "user" if i % 2 == 0 else "assistant"
                messages.append(
                    JobQuoteChat(
                        job=job,
                        message_id=f"bulk-{job.id}-{i}",
                        role=role,
                        content=f"Bulk message {i}",
                    )
                )
            JobQuoteChat.objects.bulk_create(messages)

        # Verify all messages were created
        total_messages = JobQuoteChat.objects.filter(job__in=jobs).count()
        self.assertEqual(total_messages, 60)  # 3 jobs * 20 messages each
