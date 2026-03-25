#!/usr/bin/env python
"""
Comprehensive integration test for quote chat conversation.

Tests a realistic conversation flow covering:
- CALC mode with multiple clarifications
- PRICE mode with material selection
- TABLE mode for final quote generation
- Context preservation across mode transitions
"""

import os
import sys

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
django.setup()

from apps.job.models import Job, JobQuoteChat
from apps.job.services.gemini_chat_service import GeminiChatService


def print_separator(char="=", length=70):
    """Print a separator line."""
    print(char * length)


def print_test_step(step_num, description, mode=None):
    """Print formatted test step header."""
    print_separator()
    mode_text = f" (Expected: {mode})" if mode else ""
    print(f"STEP {step_num}: {description}{mode_text}")
    print_separator()


def print_message(role, content, truncate=800):
    """Print a chat message."""
    role_label = "USER" if role == "user" else "AI"
    print(f"\n{role_label}:")
    if len(content) > truncate:
        print(f"{content[:truncate]}")
        print(f"... (truncated from {len(content)} chars)")
    else:
        print(content)


def send_message(service, job, content, step_num, description, expected_mode=None):
    """Send a message and display the response."""
    print_test_step(step_num, description, expected_mode)
    print_message("user", content)

    # Save user message
    JobQuoteChat.objects.create(
        job=job,
        message_id=f"user-test-{step_num}",
        role="user",
        content=content,
    )

    # Generate AI response
    try:
        response = service.generate_mode_response(
            job_id=str(job.id), user_message=content, mode=None
        )

        print_message("assistant", response.content)

        # Display metadata
        if response.metadata:
            print("\nMetadata:")
            if "mode" in response.metadata:
                print(f"  Mode: {response.metadata['mode']}")
            if "has_questions" in response.metadata:
                print(f"  Has questions: {response.metadata['has_questions']}")

        return response

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        return None


def main():
    """Run comprehensive quote conversation test."""
    print("\n")
    print_separator("*", 70)
    print("COMPREHENSIVE QUOTE CONVERSATION TEST")
    print_separator("*", 70)

    # Get a job to test with
    job = Job.objects.first()
    if not job:
        print("❌ No jobs found in database. Please create a job first.")
        return 1

    print(f"\nTesting with job: {job.job_number} - {job.name}")
    print(f"Client: {job.client.name}")

    # Clear existing chat
    deleted = JobQuoteChat.objects.filter(job=job).delete()
    print(f"Cleared {deleted[0]} existing chat messages\n")

    # Initialize service
    service = GeminiChatService()
    service.start_conversation()

    # =========================================================================
    # PHASE 1: CALC MODE - Initial request
    # =========================================================================
    send_message(
        service,
        job,
        "I need to quote for 5 stainless steel benchtops, each 2000mm x 600mm",
        step_num=1,
        description="Initial calculation request",
        expected_mode="CALC",
    )

    # =========================================================================
    # PHASE 2: CALC MODE - Clarification responses
    # =========================================================================
    send_message(
        service,
        job,
        "1.2mm thick 304 stainless steel with a brushed finish",
        step_num=2,
        description="Provide material specifications",
        expected_mode="CALC",
    )

    send_message(
        service,
        job,
        "They need turned down edges on all sides, 30mm return",
        step_num=3,
        description="Add fabrication details",
        expected_mode="CALC",
    )

    send_message(
        service,
        job,
        "Use 40x40x3mm RHS reinforcing underneath, spaced 400mm apart. "
        "304 stainless steel. Estimate 150mm of welding per reinforcing piece",
        step_num=4,
        description="Provide complete reinforcing specifications",
        expected_mode="CALC",
    )

    # =========================================================================
    # PHASE 3: PRICE MODE - Request pricing
    # =========================================================================
    send_message(
        service,
        job,
        "Perfect. Now let's get pricing for all the materials we've calculated",
        step_num=5,
        description="Transition to pricing mode with complete calc info",
        expected_mode="PRICE",
    )

    # =========================================================================
    # PHASE 4: PRICE MODE - Answer any clarifications
    # =========================================================================
    send_message(
        service,
        job,
        "Get pricing from local suppliers. Standard delivery is fine",
        step_num=6,
        description="Provide pricing clarifications",
        expected_mode="PRICE",
    )

    # =========================================================================
    # PHASE 5: TABLE MODE - Generate final quote
    # =========================================================================
    send_message(
        service,
        job,
        "OK, let's create the final quote table. "
        "Use $85/hour for labour, estimate 3 hours per benchtop for fabrication",
        step_num=7,
        description="Generate final quote",
        expected_mode="TABLE",
    )

    # =========================================================================
    # PHASE 6: Follow-up question (should stay in TABLE or answer contextually)
    # =========================================================================
    send_message(
        service,
        job,
        "What if we change the finish to mirror polish instead?",
        step_num=8,
        description="Ask follow-up question about variation",
        expected_mode=None,
    )

    # =========================================================================
    # Display final conversation summary
    # =========================================================================
    print("\n")
    print_separator("*", 70)
    print("CONVERSATION SUMMARY")
    print_separator("*", 70)

    messages = JobQuoteChat.objects.filter(job=job).order_by("timestamp")
    print(f"\nTotal messages: {messages.count()}")

    mode_counts = {}
    for msg in messages:
        if msg.role == "assistant" and msg.metadata:
            mode = msg.metadata.get("mode", "N/A")
            mode_counts[mode] = mode_counts.get(mode, 0) + 1

    print("\nMessages by mode:")
    for mode, count in mode_counts.items():
        print(f"  {mode}: {count} responses")

    print("\n")
    print_separator("*", 70)
    print("TEST COMPLETE")
    print_separator("*", 70)
    print("\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
