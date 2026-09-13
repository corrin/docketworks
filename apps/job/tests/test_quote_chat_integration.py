"""Real ChatKit/Agents/LiteLLM/MCP exchange with stored supplier and job facts."""

from decimal import Decimal

import pytest
from asgiref.sync import async_to_sync

from apps.job.chat.conversation import send_message
from apps.job.chat.store import ChatContext
from apps.job.models import Job, JobQuoteChat, JobQuoteChatThread
from apps.platform.observability.models import VendorCall
from apps.quoting.models import SupplierPriceList, SupplierProduct

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.mark.usefixtures("integration_credentials")
def test_real_chat_reads_tools_and_continues_stored_history(job: Job) -> None:
    """Ground a reply in catalogue facts, then retrieve the earlier fact on a new run."""
    assert job.company is not None
    price_list = SupplierPriceList.objects.create(supplier=job.company, file_name="chat-test.csv")
    SupplierProduct.objects.create(
        supplier=job.company,
        price_list=price_list,
        item_no="DW-CHAT-PRICE",
        product_name="DW-CHAT-PRICE stainless sheet",
        variant_id="sheet",
        variant_price=Decimal("73.29"),
        price_unit="per sheet",
        url="https://example.com/catalogue/DW-CHAT-PRICE",
    )
    context = ChatContext(job_id=job.id, provider_type="OpenAI")
    reply = async_to_sync(send_message)(
        context,
        "Read this job's details with job_context and look up DW-CHAT-PRICE with supplier_prices. "
        "Report the job name and the stored price and unit. Do not calculate anything.",
    )
    assert job.name in reply
    assert "73.29" in reply
    assert "sheet" in reply.lower()
    thread = JobQuoteChatThread.objects.get(job=job)
    followup = async_to_sync(send_message)(
        context, "What item code did I just ask about?", thread.id
    )
    assert "DW-CHAT-PRICE" in followup
    assert JobQuoteChat.objects.filter(thread=thread, payload__type="user_message").count() == 2
    assert (
        JobQuoteChat.objects.filter(thread=thread, payload__type="assistant_message").count() >= 2
    )
    calls = VendorCall.objects.filter(vendor=VendorCall.Vendor.LLM)
    assert calls.count() >= 3
    assert all(row.tokens_in is not None and row.tokens_in > 0 for row in calls)
