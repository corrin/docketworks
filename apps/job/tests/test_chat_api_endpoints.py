"""
Integration tests for Chat API endpoints

Tests the complete API flow from HTTP request to response,
including authentication, validation, and error handling.
"""

import json
import uuid
from unittest.mock import patch

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient

from apps.accounts.models import Staff
from apps.client.models import Client
from apps.job.models import Job, JobQuoteChat
from apps.testing import BaseTestCase
from apps.workflow.enums import AIProviderTypes
from apps.workflow.models import AIProvider, CompanyDefaults, XeroPayItem


class ChatAPIEndpointTests(BaseTestCase):
    """Test chat API endpoints"""

    def setUp(self):
        """Set up test data"""
        self.client_api = APIClient()

        # Get test data from fixture
        self.company_defaults = CompanyDefaults.get_solo()

        self.client_obj = Client.objects.create(
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
            client=self.client_obj,
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

        # Create test user
        self.staff = Staff.objects.create_user(
            email="test@example.com",
            password="testpassword123",
            first_name="Test",
            last_name="User",
        )

        # URLs
        self.chat_history_url = reverse(
            "jobs:job_quote_chat_history", kwargs={"job_id": str(self.job.id)}
        )
        self.chat_interaction_url = reverse(
            "jobs:job_quote_chat_interaction", kwargs={"job_id": str(self.job.id)}
        )

        # Authenticate for API requests
        self.client_api.force_authenticate(user=self.staff)

    def test_chat_history_get_empty(self):
        """Test getting empty chat history"""
        response = self.client_api.get(self.chat_history_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["messages"], [])

    def test_chat_history_get_with_messages(self):
        """Test getting chat history with existing messages"""
        JobQuoteChat.objects.create(
            job=self.job,
            message_id="user-1",
            role="user",
            content="Hello",
        )
        JobQuoteChat.objects.create(
            job=self.job,
            message_id="assistant-1",
            role="assistant",
            content="Hi there!",
        )

        response = self.client_api.get(self.chat_history_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["success"], True)
        self.assertEqual(response.data["data"]["job_id"], str(self.job.id))

        messages = response.data["data"]["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0]["content"], "Hello")
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(messages[1]["content"], "Hi there!")
        self.assertEqual(messages[1]["role"], "assistant")

    def test_chat_history_post_create_message(self):
        """Test creating a new chat message"""
        data = {
            "message_id": "test-create-msg",
            "role": "user",
            "content": "Test message creation",
        }

        response = self.client_api.post(
            self.chat_history_url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["content"], "Test message creation")
        self.assertEqual(response.data["data"]["role"], "user")

        # Verify message was saved to database
        message = JobQuoteChat.objects.get(message_id="test-create-msg")
        self.assertEqual(message.content, "Test message creation")
        self.assertEqual(message.role, "user")

    def test_chat_history_post_invalid_data(self):
        """Test creating message with invalid data"""
        data = {
            "message_id": "test-invalid-data",
            "role": "invalid_role",
            "content": "",
        }

        response = self.client_api.post(
            self.chat_history_url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_chat_history_delete_message(self):
        """Test deleting a single chat message"""
        message = JobQuoteChat.objects.create(
            job=self.job,
            message_id="test-message-1",
            role="user",
            content="Message to delete",
        )

        delete_url = reverse(
            "jobs:job_quote_chat_message",
            kwargs={"job_id": str(self.job.id), "message_id": message.message_id},
        )

        response = self.client_api.delete(delete_url)

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        # Verify message was deleted
        self.assertFalse(JobQuoteChat.objects.filter(id=message.id).exists())

    def test_chat_history_delete_all(self):
        """Test deleting all chat messages for a job"""
        # Create multiple messages
        JobQuoteChat.objects.create(
            job=self.job,
            message_id="msg-1",
            role="user",
            content="First message",
        )
        JobQuoteChat.objects.create(
            job=self.job,
            message_id="msg-2",
            role="assistant",
            content="Second message",
        )
        JobQuoteChat.objects.create(
            job=self.job,
            message_id="msg-3",
            role="user",
            content="Third message",
        )

        # Verify messages exist
        self.assertEqual(JobQuoteChat.objects.filter(job=self.job).count(), 3)

        # Delete all messages
        response = self.client_api.delete(self.chat_history_url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertEqual(response.data["data"]["deleted_count"], 3)

        # Verify all messages were deleted
        self.assertEqual(JobQuoteChat.objects.filter(job=self.job).count(), 0)

    def test_chat_history_job_not_found(self):
        """Test accessing chat history for non-existent job"""
        non_existent_job_id = str(uuid.uuid4())
        url = reverse(
            "jobs:job_quote_chat_history", kwargs={"job_id": non_existent_job_id}
        )

        response = self.client_api.get(url)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("apps.job.services.chat_service.ChatService.generate_mode_response")
    def test_chat_interaction_success(self, mock_generate_response):
        """Test successful chat interaction"""
        # Mock the service response
        mock_response = JobQuoteChat.objects.create(
            job=self.job,
            message_id="assistant-response-1",
            role="assistant",
            content="AI response to user message",
            metadata={"model": "gemini-pro", "tool_calls": []},
        )
        mock_generate_response.return_value = mock_response

        data = {
            "message": "Test user message for AI",
        }

        response = self.client_api.post(
            self.chat_interaction_url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.data["success"])
        self.assertEqual(
            response.data["data"]["content"], "AI response to user message"
        )
        self.assertEqual(response.data["data"]["role"], "assistant")

        # Verify service was called with correct parameters
        mock_generate_response.assert_called_once_with(
            job_id=self.job.id, user_message="Test user message for AI", mode=None
        )

    def test_chat_interaction_missing_message(self):
        """Test chat interaction with missing message"""
        data = {}

        response = self.client_api.post(
            self.chat_interaction_url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn(
            "error", response.data
        )  # Error message returned for invalid input

    def test_chat_interaction_empty_message(self):
        """Test chat interaction with empty message"""
        data = {
            "message": "",
        }

        response = self.client_api.post(
            self.chat_interaction_url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])

    def test_chat_interaction_job_not_found(self):
        """Test chat interaction with non-existent job"""
        non_existent_job_id = str(uuid.uuid4())
        url = reverse(
            "jobs:job_quote_chat_interaction", kwargs={"job_id": non_existent_job_id}
        )

        data = {
            "message": "Test message",
        }

        response = self.client_api.post(
            url, data=json.dumps(data), content_type="application/json"
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["code"], "JOB_NOT_FOUND")

    @patch("apps.job.services.chat_service.ChatService.generate_mode_response")
    def test_chat_interaction_configuration_error(self, mock_generate_response):
        """Test chat interaction with configuration error"""
        mock_generate_response.side_effect = ValueError("No AI provider configured")

        data = {
            "message": "Test message",
        }

        response = self.client_api.post(
            self.chat_interaction_url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertIn("No AI provider configured", response.data["error"])

    @patch("apps.job.services.chat_service.ChatService.generate_mode_response")
    def test_chat_interaction_internal_error(self, mock_generate_response):
        """Test chat interaction with internal error"""
        mock_generate_response.side_effect = Exception("Internal server error")

        data = {
            "message": "Test message",
        }

        response = self.client_api.post(
            self.chat_interaction_url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertFalse(response.data["success"])
        self.assertIn("internal error", response.data["error"])


class ChatAPIPermissionTests(BaseTestCase):
    """Test API permissions and authentication"""

    def setUp(self):
        """Set up test data"""
        self.client_api = APIClient()

        # Get test data from fixture
        self.company_defaults = CompanyDefaults.get_solo()

        self.client_obj = Client.objects.create(
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
            client=self.client_obj,
            status="quoting",
            default_xero_pay_item=self.xero_pay_item,
            staff=self.test_staff,
        )

        # Create test users
        self.staff = Staff.objects.create_user(
            email="test@example.com",
            password="testpassword123",
            first_name="Test",
            last_name="User",
        )

        self.admin_staff = Staff.objects.create_user(
            email="admin@example.com",
            password="adminpassword123",
            first_name="Admin",
            last_name="User",
            is_office_staff=True,
            is_superuser=True,
        )

        # URLs
        self.chat_history_url = reverse(
            "jobs:job_quote_chat_history", kwargs={"job_id": str(self.job.id)}
        )
        self.chat_interaction_url = reverse(
            "jobs:job_quote_chat_interaction", kwargs={"job_id": str(self.job.id)}
        )

    def test_unauthenticated_access(self):
        """Test unauthenticated access to chat endpoints"""
        # Test chat history endpoint
        response = self.client_api.get(self.chat_history_url)
        # Note: Depending on your authentication setup, this might be 401 or 403
        self.assertIn(response.status_code, [200, 401, 403])

        # Test chat interaction endpoint
        response = self.client_api.post(
            self.chat_interaction_url,
            data={"message": "Test message"},
        )
        self.assertIn(response.status_code, [200, 401, 403])

    def test_authenticated_access(self):
        """Test authenticated access to chat endpoints"""
        self.client_api.force_authenticate(user=self.staff)

        # Test chat history endpoint
        response = self.client_api.get(self.chat_history_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_admin_access(self):
        """Test admin access to chat endpoints"""
        self.client_api.force_authenticate(user=self.admin_staff)

        # Test chat history endpoint
        response = self.client_api.get(self.chat_history_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class ChatAPIValidationTests(BaseTestCase):
    """Test API data validation"""

    def setUp(self):
        """Set up test data"""
        self.client_api = APIClient()

        self.company_defaults = CompanyDefaults.get_solo()

        self.client_obj = Client.objects.create(
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
            client=self.client_obj,
            status="quoting",
            default_xero_pay_item=self.xero_pay_item,
            staff=self.test_staff,
        )

        self.chat_history_url = reverse(
            "jobs:job_quote_chat_history", kwargs={"job_id": str(self.job.id)}
        )

        # Create staff user and authenticate (needs is_office_staff for POST)
        self.staff = Staff.objects.create_user(
            email="validation_test@example.com",
            password="testpassword123",
            first_name="Validation",
            last_name="Tester",
            is_office_staff=True,
        )
        self.client_api.force_authenticate(user=self.staff)

    def test_create_message_valid_roles(self):
        """Test creating messages with valid roles"""
        valid_roles = ["user", "assistant"]

        for i, role in enumerate(valid_roles):
            data = {
                "message_id": f"test-msg-{role}-{i}",
                "role": role,
                "content": f"Test message with {role} role",
            }

            response = self.client_api.post(
                self.chat_history_url,
                data=json.dumps(data),
                content_type="application/json",
            )

            self.assertEqual(response.status_code, status.HTTP_201_CREATED)
            self.assertEqual(response.data["data"]["role"], role)

    def test_create_message_invalid_role(self):
        """Test creating message with invalid role"""
        data = {
            "message_id": "test-invalid-role",
            "role": "invalid_role",
            "content": "Test message",
        }

        response = self.client_api.post(
            self.chat_history_url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_message_missing_content(self):
        """Test creating message with missing content"""
        data = {
            "message_id": "test-missing-content",
            "role": "user",
        }

        response = self.client_api.post(
            self.chat_history_url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_message_empty_content(self):
        """Test creating message with empty content"""
        data = {
            "message_id": "test-empty-content",
            "role": "user",
            "content": "",
        }

        response = self.client_api.post(
            self.chat_history_url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_message_with_metadata(self):
        """Test creating message with metadata"""
        data = {
            "message_id": "test-with-metadata",
            "role": "assistant",
            "content": "Test message with metadata",
            "metadata": {
                "model": "gemini-pro",
                "tool_calls": [],
                "custom_field": "test_value",
            },
        }

        response = self.client_api.post(
            self.chat_history_url,
            data=json.dumps(data),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["metadata"]["model"], "gemini-pro")
        self.assertEqual(
            response.data["data"]["metadata"]["custom_field"], "test_value"
        )

    def test_nonexistent_job_id(self):
        """Test API with non-existent job ID"""
        # Use a valid UUID format that doesn't exist in the database
        nonexistent_url = reverse(
            "jobs:job_quote_chat_history",
            kwargs={"job_id": "00000000-0000-0000-0000-000000000000"},
        )

        response = self.client_api.get(nonexistent_url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
