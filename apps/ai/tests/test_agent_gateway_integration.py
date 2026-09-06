"""Prove SDK tool calls, streaming and usage against the configured vendor."""

import pytest
from agents import Agent, RunConfig, Runner, function_tool
from asgiref.sync import async_to_sync

from apps.ai.services.llm_client import (
    AgentCallRecording,
    agent_model,
    agent_model_settings,
    resolve_target,
)
from apps.platform.observability.models import VendorCall

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


@pytest.mark.usefixtures("integration_credentials")
def test_streaming_tools_record_each_vendor_round_trip() -> None:
    """A real tool invocation survives both adapters and is separately metered."""
    target = resolve_target("OpenAI")
    calls: list[str] = []

    @function_tool
    def lookup_price(item_code: str) -> str:
        """Look up the current supplier price for an item code."""
        calls.append(item_code)
        return "73.29 NZD per sheet"

    async def run() -> None:
        agent = Agent[None](
            name="Gateway integration test",
            instructions="Call lookup_price for item DW-TEST. Report the returned price.",
            model=agent_model(target),
            model_settings=agent_model_settings(),
            tools=[lookup_price],
        )
        result = Runner.run_streamed(
            agent,
            "Look up DW-TEST now.",
            hooks=AgentCallRecording[None](target),
            run_config=RunConfig(tracing_disabled=True),
            max_turns=3,
        )
        events = [event async for event in result.stream_events()]
        assert events
        assert calls == ["DW-TEST"]
        assert "73.29" in result.final_output

    VendorCall.objects.all().delete()
    async_to_sync(run)()
    rows = list(VendorCall.objects.filter(vendor=VendorCall.Vendor.LLM))
    assert len(rows) == 2
    assert all(row.tokens_in is not None and row.tokens_in > 0 for row in rows)
    assert all(row.tokens_out is not None and row.tokens_out > 0 for row in rows)
    assert all(row.model_name == target.model for row in rows)
