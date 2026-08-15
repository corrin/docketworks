#!/usr/bin/env python
"""Comprehensive quote-chat conversation harness.

Drives a realistic multi-phase quoting conversation — calculation,
clarifications, pricing, final quote table, then a variation question —
through the JobQuoteChat + ADR 0041 gateway plumbing in
scripts/ops/quote_chat_harness.py. v1 asserted CALC/PRICE/TABLE mode
transitions from its Gemini service; that machinery is not ported, so this
checks context preservation across the same conversation shape instead.

Usage:
    uv run python -m scripts.ops.full_quote_conversation_harness
"""

import sys

from scripts.bootstrap import setup_django

setup_django()

from apps.job.models import Job  # noqa: E402 -- Django must be configured first
from scripts.ops.quote_chat_harness import (  # noqa: E402
    clear_chat,
    send_message,
)

# (description, message) per conversation step.
STEPS = [
    (
        "Initial calculation request",
        "I need to quote for 5 stainless steel benchtops, each 2000mm x 600mm",
    ),
    (
        "Provide material specifications",
        "1.2mm thick 304 stainless steel with a brushed finish",
    ),
    (
        "Add fabrication details",
        "They need turned down edges on all sides, 30mm return",
    ),
    (
        "Provide complete reinforcing specifications",
        (
            "Use 40x40x3mm RHS reinforcing underneath, spaced 400mm apart. "
            "304 stainless steel. Estimate 150mm of welding per reinforcing piece"
        ),
    ),
    (
        "Transition to pricing with complete calc info",
        "Perfect. Now let's get pricing for all the materials we've calculated",
    ),
    (
        "Provide pricing clarifications",
        "Get pricing from local suppliers. Standard delivery is fine",
    ),
    (
        "Generate final quote",
        (
            "OK, let's create the final quote table. "
            "Use $85/hour for labour, estimate 3 hours per benchtop for fabrication"
        ),
    ),
    (
        "Ask follow-up question about variation",
        "What if we change the finish to mirror polish instead?",
    ),
]


def print_separator(char: str = "=", length: int = 70) -> None:
    """Print a separator line."""
    print(char * length)


def print_message(role: str, content: str, truncate: int = 800) -> None:
    """Print a chat message, truncating long bodies."""
    role_label = "USER" if role == "user" else "AI"
    print(f"\n{role_label}:")
    if len(content) > truncate:
        print(content[:truncate])
        print(f"... (truncated from {len(content)} chars)")
    else:
        print(content)


def main() -> int:
    print("\n")
    print_separator("*")
    print("COMPREHENSIVE QUOTE CONVERSATION TEST")
    print_separator("*")

    job = Job.objects.first()
    if not job:
        print("No jobs found in database. Please create a job first.")
        return 1

    print(f"\nTesting with job: {job.job_number} - {job.name}")
    print(f"Company: {job.company.name if job.company else 'none (shop job)'}")

    cleared = clear_chat(job)
    print(f"Cleared {cleared} existing chat messages\n")

    for step_num, (description, content) in enumerate(STEPS, 1):
        print_separator()
        print(f"STEP {step_num}: {description}")
        print_separator()
        print_message("user", content)
        reply = send_message(job, content)
        print_message("assistant", reply)

    print("\n")
    print_separator("*")
    print("CONVERSATION SUMMARY")
    print_separator("*")
    print(f"\nTotal messages: {job.quote_chat_messages.count()}")

    print("\n")
    print_separator("*")
    print("TEST COMPLETE")
    print_separator("*")
    print("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
