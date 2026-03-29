"""
Unit tests for JobQuoteChat model constraints.
"""

from django.db import IntegrityError
from django.utils import timezone

from apps.client.models import Client
from apps.job.models import Job, JobQuoteChat
from apps.testing import BaseTestCase
from apps.workflow.models import CompanyDefaults, XeroPayItem


class JobQuoteChatModelTests(BaseTestCase):
    """Test JobQuoteChat model constraints"""

    def setUp(self):
        """Set up test data"""
        self.company_defaults = CompanyDefaults.get_solo()

        self.client = Client.objects.create(
            name="Test Client",
            email="client@example.com",
            phone="0123456789",
            xero_last_modified=timezone.now(),
        )

        self.xero_pay_item = XeroPayItem.get_ordinary_time()

        self.job = Job.objects.create(
            name="Test Job",
            description="Test job description",
            client=self.client,
            default_xero_pay_item=self.xero_pay_item,
        )

    def test_message_id_uniqueness(self):
        """Test that message_id must be unique"""
        JobQuoteChat.objects.create(
            job=self.job,
            message_id="unique-message-id",
            role="user",
            content="First message",
        )

        with self.assertRaises(IntegrityError):
            JobQuoteChat.objects.create(
                job=self.job,
                message_id="unique-message-id",
                role="assistant",
                content="Second message with same ID",
            )
