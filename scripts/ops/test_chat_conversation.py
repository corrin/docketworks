#!/usr/bin/env python
"""Exercise a job's quote chat without the frontend.

Persists user messages on JobQuoteChat and generates assistant replies
through the single LLM gateway (ADR 0041); see
scripts/ops/quote_chat_harness.py for what this does and does not cover
relative to v1's Gemini mode machinery.

Usage:
    uv run python scripts/ops/test_chat_conversation.py                       # multi-turn test
    uv run python scripts/ops/test_chat_conversation.py --test simple         # pricing scenario
"""

import argparse
import os
import sys
from pathlib import Path

# scripts/ops/ is two levels below the repo root; see
# scripts/ops/setup_dev_logins.py for why this is inserted explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

import django

django.setup()

from apps.job.models import Job  # noqa: E402 -- Django must be configured first
from scripts.ops.quote_chat_harness import (  # noqa: E402
    clear_chat,
    print_history,
    send_message,
)


def get_test_job() -> Job:
    """A job to chat against, refusing to run on an empty database."""
    job = Job.objects.first()
    if not job:
        raise SystemExit("No jobs found in database. Please create a job first.")
    return job


def test_simple_scenario() -> None:
    """The adaptor-square pricing scenario: a request, then a confused follow-up."""
    job = get_test_job()

    print(f"\n{'=' * 60}")
    print("USER SCENARIO TEST: Adaptor Square Pricing")
    print("=" * 60)
    print(f"Testing with job: {job.job_number} - {job.name}\n")

    cleared = clear_chat(job)
    print(f"Cleared {cleared} existing chat messages")

    steps = [
        "How much for a single adaptor square - 100x100 - 1.2m MS",
        "I don't understand your question? That's what I'm asking you?",
    ]
    for i, user_msg in enumerate(steps, 1):
        print("=" * 60)
        print(f"MESSAGE {i}")
        print("=" * 60)
        print(f"User: {user_msg}\n")
        reply = send_message(job, user_msg)
        print(f"AI: {reply}\n")

    print("=" * 60)
    print("USER SCENARIO TEST COMPLETE")
    print("=" * 60)


def test_conversation() -> None:
    """A multi-turn conversation checking context is preserved across turns."""
    job = get_test_job()

    print(f"Testing with job: {job.job_number} - {job.name}")
    print("=" * 60)

    cleared = clear_chat(job)
    print(f"Cleared {cleared} existing chat messages")

    test_messages = [
        {
            "content": "3 stainless steel boxes, 700x700x400mm, welded seams",
            "description": "Initial request",
        },
        {
            "content": "0.8mm 304 stainless, open top",
            "description": "Follow-up with more details - should remember context",
        },
        {
            "content": "Good. Let's price it",
            "description": "Request pricing - should carry the calculated context",
        },
    ]

    for i, test in enumerate(test_messages, 1):
        print(f"\n{'=' * 60}")
        print(f"TEST {i}: {test['description']}")
        print(f"{'=' * 60}")
        print(f"User: {test['content']}")
        print("-" * 40)

        reply = send_message(job, test["content"])

        print("Assistant response (first 500 chars):")
        print(reply[:500])
        if len(reply) > 500:
            print(f"... (truncated, total length: {len(reply)} chars)")

    print(f"\n{'=' * 60}")
    print("FINAL CHAT HISTORY IN DATABASE")
    print("=" * 60)
    total = print_history(job)
    print(f"\nTotal messages in conversation: {total}")
    print("\nTest complete!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Test chat conversation scenarios")
    parser.add_argument(
        "--test",
        type=str,
        choices=["conversation", "simple"],
        default="conversation",
        help="Which test to run (default: conversation)",
    )
    parser.add_argument(
        "--with-file",
        type=str,
        help="Unsupported: see the error it raises",
    )
    args = parser.parse_args()

    if args.with_file:
        # v1 attached a JobFile and had Gemini read its content. The ADR 0041
        # gateway is text-only today, so a file leg here would silently test
        # nothing; refuse until the gateway grows attachment support.
        raise SystemExit(
            "--with-file is not supported: apps/ai's chat_completion gateway is "
            "text-only (no attachment support yet), so file-content analysis "
            "cannot be exercised. blocked-by: ai-gateway-attachments"
        )

    if args.test == "simple":
        test_simple_scenario()
    else:
        test_conversation()


if __name__ == "__main__":
    main()
