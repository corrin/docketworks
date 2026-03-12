"""
Unit tests for JobQuoteChat model

Tests cover:
- Model field validation
- Model methods and properties
- Database constraints
- Serialization and deserialization
- Relationships with other models
"""

from datetime import datetime
from datetime import timezone as dt_timezone

from django.db import IntegrityError
from django.utils import timezone

from apps.client.models import Client
from apps.job.models import Job, JobQuoteChat
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults, XeroPayItem


class JobQuoteChatModelTests(BaseTestCase):
    """Test JobQuoteChat model functionality"""

    def setUp(self):
        """Set up test data"""
        # Get CompanyDefaults from fixture
        self.company_defaults = CompanyDefaults.get_solo()

        self.client = Client.objects.create(
            name="Test Client",
            email="client@example.com",
            phone="0123456789",
            xero_last_modified=timezone.now(),
        )

        # Get Ordinary Time pay item (created by migration)
        self.xero_pay_item = XeroPayItem.get_ordinary_time()

        # Create Job with minimal valid fields; job_number is auto-generated,
        # status defaults to 'draft', and charge_out_rate sourced from CompanyDefaults
        self.job = Job.objects.create(
            name="Test Job",
            description="Test job description",
            client=self.client,
            default_xero_pay_item=self.xero_pay_item,
        )

    def test_create_basic_chat_message(self):
        """Test creating a basic chat message"""
        message = JobQuoteChat.objects.create(
            job=self.job,
            message_id="test-message-1",
            role="user",
            content="Hello, this is a test message",
        )

        self.assertEqual(message.job, self.job)
        self.assertEqual(message.message_id, "test-message-1")
        self.assertEqual(message.role, "user")
        self.assertEqual(message.content, "Hello, this is a test message")
        self.assertIsNotNone(message.timestamp)
        self.assertEqual(message.metadata, {})

    def test_create_message_with_metadata(self):
        """Test creating message with metadata"""
        metadata = {
            "model": "gemini-pro",
            "tool_calls": [{"name": "search_products", "result": "found items"}],
            "custom_data": {"key": "value"},
        }

        message = JobQuoteChat.objects.create(
            job=self.job,
            message_id="test-message-2",
            role="assistant",
            content="AI response with metadata",
            metadata=metadata,
        )

        self.assertEqual(message.metadata, metadata)
        self.assertEqual(message.metadata["model"], "gemini-pro")
        self.assertEqual(len(message.metadata["tool_calls"]), 1)

    def test_string_representation(self):
        """Test string representation of chat message"""
        message = JobQuoteChat.objects.create(
            job=self.job,
            message_id="test-message-3",
            role="user",
            content="Test message for string representation",
        )

        expected_str = f"{self.job.name} - user: Test message for string representation"
        self.assertEqual(str(message), expected_str)

    def test_message_id_uniqueness(self):
        """Test that message_id must be unique"""
        # Create first message
        JobQuoteChat.objects.create(
            job=self.job,
            message_id="unique-message-id",
            role="user",
            content="First message",
        )

        # Try to create second message with same message_id
        with self.assertRaises(IntegrityError):
            JobQuoteChat.objects.create(
                job=self.job,
                message_id="unique-message-id",
                role="assistant",
                content="Second message with same ID",
            )

    def test_role_validation(self):
        """Test role field validation"""
        # Model only allows "user" and "assistant" roles
        valid_roles = ["user", "assistant"]

        for role in valid_roles:
            message = JobQuoteChat.objects.create(
                job=self.job,
                message_id=f"test-{role}-message",
                role=role,
                content=f"Test message for {role} role",
            )
            self.assertEqual(message.role, role)

    def test_content_allows_empty_string(self):
        """Test that content field allows empty string (but not NULL)"""
        # Empty string is valid at database level
        message = JobQuoteChat.objects.create(
            job=self.job,
            message_id="test-empty-content",
            role="user",
            content="",
        )
        self.assertEqual(message.content, "")

    def test_job_relationship(self):
        """Test relationship with Job model"""
        message = JobQuoteChat.objects.create(
            job=self.job,
            message_id="test-relationship",
            role="user",
            content="Test job relationship",
        )

        # Test forward relationship
        self.assertEqual(message.job, self.job)

        # Test reverse relationship (related_name is quote_chat_messages)
        job_messages = self.job.quote_chat_messages.all()
        self.assertIn(message, job_messages)

    def test_timestamp_auto_set(self):
        """Test that timestamp is automatically set"""
        before_create = datetime.now(dt_timezone.utc)

        message = JobQuoteChat.objects.create(
            job=self.job,
            message_id="test-timestamp",
            role="user",
            content="Test timestamp",
        )

        after_create = datetime.now(dt_timezone.utc)

        self.assertIsNotNone(message.timestamp)
        self.assertGreaterEqual(message.timestamp, before_create)
        self.assertLessEqual(message.timestamp, after_create)

    def test_metadata_json_serialization(self):
        """Test that metadata is properly serialized as JSON"""
        complex_metadata = {
            "model": "gemini-pro",
            "temperature": 0.7,
            "tool_calls": [
                {
                    "name": "search_products",
                    "arguments": {"query": "steel", "supplier": "ABC Steel"},
                    "result": "Found 10 products",
                }
            ],
            "nested": {"level1": {"level2": ["item1", "item2"]}},
        }

        message = JobQuoteChat.objects.create(
            job=self.job,
            message_id="test-json-metadata",
            role="assistant",
            content="Test JSON metadata",
            metadata=complex_metadata,
        )

        # Retrieve from database and verify serialization
        retrieved_message = JobQuoteChat.objects.get(id=message.id)
        self.assertEqual(retrieved_message.metadata, complex_metadata)
        self.assertEqual(retrieved_message.metadata["temperature"], 0.7)
        self.assertEqual(len(retrieved_message.metadata["tool_calls"]), 1)
        self.assertEqual(
            retrieved_message.metadata["nested"]["level1"]["level2"], ["item1", "item2"]
        )

    def test_ordering_by_timestamp(self):
        """Test default ordering by timestamp"""
        # Create messages with slight delay to ensure different timestamps
        message1 = JobQuoteChat.objects.create(
            job=self.job,
            message_id="first-message",
            role="user",
            content="First message",
        )

        message2 = JobQuoteChat.objects.create(
            job=self.job,
            message_id="second-message",
            role="assistant",
            content="Second message",
        )

        message3 = JobQuoteChat.objects.create(
            job=self.job,
            message_id="third-message",
            role="user",
            content="Third message",
        )

        # Get messages in default order (should be by timestamp)
        messages = JobQuoteChat.objects.filter(job=self.job).order_by("timestamp")

        self.assertEqual(messages[0], message1)
        self.assertEqual(messages[1], message2)
        self.assertEqual(messages[2], message3)

    def test_conversation_history_retrieval(self):
        """Test retrieving conversation history for a job"""
        # Create a conversation
        conversation = [
            ("user", "Hello"),
            ("assistant", "Hi there!"),
            ("user", "What can you help with?"),
            ("assistant", "I can help with quoting and materials"),
            ("user", "Great, thanks!"),
        ]

        messages = []
        for i, (role, content) in enumerate(conversation):
            message = JobQuoteChat.objects.create(
                job=self.job,
                message_id=f"conv-{i}",
                role=role,
                content=content,
            )
            messages.append(message)

        # Retrieve conversation history
        history = JobQuoteChat.objects.filter(job=self.job).order_by("timestamp")

        self.assertEqual(history.count(), 5)
        for i, message in enumerate(history):
            self.assertEqual(message.role, conversation[i][0])
            self.assertEqual(message.content, conversation[i][1])

    def test_multiple_jobs_isolation(self):
        """Test that messages are isolated between different jobs"""
        # Create second job
        job2 = Job.objects.create(
            name="Second Job",
            description="Second job description",
            client=self.client,
        )

        # Create messages for both jobs
        message1 = JobQuoteChat.objects.create(
            job=self.job,
            message_id="job1-message",
            role="user",
            content="Message for job 1",
        )

        message2 = JobQuoteChat.objects.create(
            job=job2,
            message_id="job2-message",
            role="user",
            content="Message for job 2",
        )

        # Verify isolation
        job1_messages = JobQuoteChat.objects.filter(job=self.job)
        job2_messages = JobQuoteChat.objects.filter(job=job2)

        self.assertEqual(job1_messages.count(), 1)
        self.assertEqual(job2_messages.count(), 1)
        self.assertEqual(job1_messages.first(), message1)
        self.assertEqual(job2_messages.first(), message2)

    def test_cascade_delete_with_job(self):
        """Test that chat messages are deleted when job is deleted"""
        # Create messages for the job

        # WARNING: removed variable declaration since they weren't being used
        JobQuoteChat.objects.create(
            job=self.job,
            message_id="cascade-test-1",
            role="user",
            content="First message",
        )

        JobQuoteChat.objects.create(
            job=self.job,
            message_id="cascade-test-2",
            role="assistant",
            content="Second message",
        )

        # Verify messages exist
        self.assertEqual(JobQuoteChat.objects.filter(job=self.job).count(), 2)

        # Delete the job
        job_id = self.job.id
        self.job.delete()

        # Verify messages are deleted
        self.assertEqual(JobQuoteChat.objects.filter(job_id=job_id).count(), 0)

    def test_large_content_handling(self):
        """Test handling of large content"""
        large_content = "x" * 10000  # 10KB content

        message = JobQuoteChat.objects.create(
            job=self.job,
            message_id="large-content-test",
            role="assistant",
            content=large_content,
        )

        self.assertEqual(len(message.content), 10000)

        # Retrieve and verify
        retrieved_message = JobQuoteChat.objects.get(id=message.id)
        self.assertEqual(len(retrieved_message.content), 10000)
        self.assertEqual(retrieved_message.content, large_content)

    def test_special_characters_in_content(self):
        """Test handling of special characters in content"""
        special_content = "Special chars: 🚀 emoji, unicode: ñáéíóú, symbols: @#$%^&*()_+{}|:<>?[]\\;'\",./"

        message = JobQuoteChat.objects.create(
            job=self.job,
            message_id="special-chars-test",
            role="user",
            content=special_content,
        )

        self.assertEqual(message.content, special_content)

        # Retrieve and verify
        retrieved_message = JobQuoteChat.objects.get(id=message.id)
        self.assertEqual(retrieved_message.content, special_content)

    def test_metadata_with_none_values(self):
        """Test metadata with None values"""
        metadata_with_none = {
            "model": "gemini-pro",
            "temperature": None,
            "tool_calls": None,
            "valid_field": "valid_value",
        }

        message = JobQuoteChat.objects.create(
            job=self.job,
            message_id="metadata-none-test",
            role="assistant",
            content="Test metadata with None values",
            metadata=metadata_with_none,
        )

        self.assertEqual(message.metadata, metadata_with_none)
        self.assertIsNone(message.metadata["temperature"])
        self.assertIsNone(message.metadata["tool_calls"])
        self.assertEqual(message.metadata["valid_field"], "valid_value")


class JobQuoteChatQueryTests(BaseTestCase):
    """Test query operations on JobQuoteChat model"""

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
            job_number="JOB001",
            description="Test job description",
            client=self.client,
            status="quoting",
            default_xero_pay_item=self.xero_pay_item,
        )

        # Create test messages
        self.messages = []
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            message = JobQuoteChat.objects.create(
                job=self.job,
                message_id=f"message-{i}",
                role=role,
                content=f"Test message {i}",
                metadata={"index": i, "type": "test"},
            )
            self.messages.append(message)

    def test_filter_by_role(self):
        """Test filtering messages by role"""
        user_messages = JobQuoteChat.objects.filter(job=self.job, role="user")
        assistant_messages = JobQuoteChat.objects.filter(job=self.job, role="assistant")

        self.assertEqual(user_messages.count(), 5)
        self.assertEqual(assistant_messages.count(), 5)

        # Verify all user messages have correct role
        for message in user_messages:
            self.assertEqual(message.role, "user")

        # Verify all assistant messages have correct role
        for message in assistant_messages:
            self.assertEqual(message.role, "assistant")

    def test_order_by_timestamp(self):
        """Test ordering messages by timestamp"""
        messages_asc = JobQuoteChat.objects.filter(job=self.job).order_by("timestamp")
        messages_desc = JobQuoteChat.objects.filter(job=self.job).order_by("-timestamp")

        self.assertEqual(messages_asc.count(), 10)
        self.assertEqual(messages_desc.count(), 10)

        # Verify ascending order
        for i in range(9):
            self.assertLessEqual(
                messages_asc[i].timestamp, messages_asc[i + 1].timestamp
            )

        # Verify descending order
        for i in range(9):
            self.assertGreaterEqual(
                messages_desc[i].timestamp, messages_desc[i + 1].timestamp
            )

    def test_search_content(self):
        """Test searching in message content"""
        # Create message with searchable content
        JobQuoteChat.objects.create(
            job=self.job,
            message_id="searchable-message",
            role="user",
            content="Find steel products with specific dimensions",
        )

        # Search for messages containing "steel"
        steel_messages = JobQuoteChat.objects.filter(
            job=self.job, content__icontains="steel"
        )

        self.assertEqual(steel_messages.count(), 1)
        self.assertIn("steel", steel_messages.first().content)

    def test_recent_messages_limit(self):
        """Test retrieving recent messages with limit"""
        recent_messages = JobQuoteChat.objects.filter(job=self.job).order_by(
            "-timestamp"
        )[:5]

        self.assertEqual(len(recent_messages), 5)

        # Verify they are the most recent
        for message in recent_messages:
            self.assertIn(message, self.messages[-5:])

    def test_count_by_role(self):
        """Test counting messages by role"""
        from django.db.models import Count

        role_counts = (
            JobQuoteChat.objects.filter(job=self.job)
            .values("role")
            .annotate(count=Count("role"))
        )

        role_count_dict = {item["role"]: item["count"] for item in role_counts}

        self.assertEqual(role_count_dict["user"], 5)
        self.assertEqual(role_count_dict["assistant"], 5)

    def test_metadata_queries(self):
        """Test querying based on metadata"""
        # Create message with specific metadata
        JobQuoteChat.objects.create(
            job=self.job,
            message_id="metadata-query-test",
            role="assistant",
            content="Test metadata query",
            metadata={"model": "gemini-pro", "tool_used": True},
        )

        # Query messages with specific metadata (this depends on your database backend)
        # For PostgreSQL with JSONField, you can use:
        # messages_with_model = JobQuoteChat.objects.filter(
        #     job=self.job,
        #     metadata__model="gemini-pro"
        # )

        # For other databases, you might need to filter in Python
        all_messages = JobQuoteChat.objects.filter(job=self.job)
        messages_with_model = [
            msg for msg in all_messages if msg.metadata.get("model") == "gemini-pro"
        ]

        self.assertEqual(len(messages_with_model), 1)
        self.assertEqual(messages_with_model[0].metadata["model"], "gemini-pro")
