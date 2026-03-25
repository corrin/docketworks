#!/usr/bin/env python
"""
Test script for quote chat conversation without frontend.
Run with: python scripts/test_chat_conversation.py [--with-file PATH]
"""

import argparse
import os
import shutil
import uuid

import django

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
django.setup()

from apps.job.helpers import get_job_folder_path
from apps.job.models import Job, JobFile, JobQuoteChat
from apps.job.services.gemini_chat_service import GeminiChatService


def test_simple_scenario():
    """Test the specific user scenario with adaptor square pricing."""
    job = Job.objects.first()
    if not job:
        print("No jobs found in database")
        return

    print(f"\n{'=' * 60}")
    print("USER SCENARIO TEST: Adaptor Square Pricing")
    print("=" * 60)
    print(f"Testing with job: {job.job_number} - {job.name}\n")

    # Clear existing chat
    JobQuoteChat.objects.filter(job=job).delete()

    service = GeminiChatService()
    service.start_conversation()

    # Message 1: User asks for pricing
    print("=" * 60)
    print("MESSAGE 1")
    print("=" * 60)
    user_msg_1 = "How much for a single adaptor square - 100x100 - 1.2m MS"
    print(f"User: {user_msg_1}\n")

    JobQuoteChat.objects.create(
        job=job, message_id="user-1", role="user", content=user_msg_1
    )

    try:
        response_1 = service.generate_mode_response(
            job_id=str(job.id), user_message=user_msg_1, mode=None
        )
        print(f"AI: {response_1.content}\n")
        print(f"Mode: {response_1.metadata.get('mode')}")
        print(f"Has questions: {response_1.metadata.get('has_questions')}\n")
    except Exception as e:
        print(f"ERROR: {e}\n")
        return

    # Message 2: User's confused response
    print("=" * 60)
    print("MESSAGE 2")
    print("=" * 60)
    user_msg_2 = "I don't understand your question? That's what I'm asking you?"
    print(f"User: {user_msg_2}\n")

    JobQuoteChat.objects.create(
        job=job, message_id="user-2", role="user", content=user_msg_2
    )

    try:
        response_2 = service.generate_mode_response(
            job_id=str(job.id), user_message=user_msg_2, mode=None
        )
        print(f"AI: {response_2.content}\n")
        print(f"Mode: {response_2.metadata.get('mode')}")
        print(f"Has questions: {response_2.metadata.get('has_questions')}\n")

        if "error" in response_2.metadata:
            print(f"ERROR in metadata: {response_2.metadata.get('error_message')}")
    except Exception as e:
        print(f"ERROR: {e}\n")
        import traceback

        traceback.print_exc()

    print("=" * 60)
    print("USER SCENARIO TEST COMPLETE")
    print("=" * 60)


def test_conversation(file_path=None):
    """Test a multi-turn conversation with context preservation."""

    # Get a job to test with
    job = Job.objects.first()
    if not job:
        print("No jobs found in database. Please create a job first.")
        return

    print(f"Testing with job: {job.job_number} - {job.name}")
    print("=" * 60)

    # Clear any existing chat for clean test
    deleted = JobQuoteChat.objects.filter(job=job).delete()
    print(f"Cleared {deleted[0]} existing chat messages")

    # Handle file attachment if provided
    job_file = None
    if file_path:
        print(f"\nFile attachment requested: {file_path}")
        if not os.path.exists(file_path):
            print(f"ERROR: File not found at: {file_path}")
            return

        print(f"File size: {os.path.getsize(file_path)} bytes")

        # Get job folder and copy file
        job_folder = get_job_folder_path(job.job_number)
        os.makedirs(job_folder, exist_ok=True)

        filename = os.path.basename(file_path)
        dest_path = os.path.join(job_folder, filename)
        shutil.copy(file_path, dest_path)
        print(f"Copied file to: {dest_path}")

        # Determine MIME type
        mime_type = "application/pdf" if filename.lower().endswith(".pdf") else None
        if filename.lower().endswith((".jpg", ".jpeg")):
            mime_type = "image/jpeg"
        elif filename.lower().endswith(".png"):
            mime_type = "image/png"

        # Create JobFile record
        job_file = JobFile.objects.create(
            job=job,
            filename=filename,
            file_path=filename,
            mime_type=mime_type or "application/octet-stream",
            status="active",
        )
        print(f"Created JobFile record: {job_file.id}")

        # Create upload message
        JobQuoteChat.objects.create(
            job=job,
            message_id=f"user-file-upload-{uuid.uuid4()}",
            role="user",
            content=f"Uploaded: {filename}",
            metadata={"file_ids": [str(job_file.id)], "filenames": [filename]},
        )
        print("Created upload message with file attachment\n")

    # Initialize the service
    service = GeminiChatService()
    service.start_conversation()

    # Test conversations - adjust if file was provided
    if job_file:
        test_messages = [
            {
                "content": "What is in this document? Summarize the key information.",
                "expected_mode": None,
                "description": "Ask AI to analyze the uploaded file",
            },
        ]
    else:
        test_messages = [
            {
                "content": "3 stainless steel boxes, 700×700×400mm, welded seams",
                "expected_mode": "CALC",
                "description": "Initial request - should trigger CALC mode",
            },
            {
                "content": "0.8mm 304 stainless, open top",
                "expected_mode": "CALC",
                "description": "Follow-up with more details - should remember context",
            },
            {
                "content": "Good. Let's price it",
                "expected_mode": "PRICE",
                "description": "Request pricing - should trigger PRICE mode with context",
            },
        ]

    for i, test in enumerate(test_messages, 1):
        print(f"\n{'=' * 60}")
        print(f"TEST {i}: {test['description']}")
        print(f"Expected mode: {test['expected_mode']}")
        print(f"{'=' * 60}")
        print(f"User: {test['content']}")
        print("-" * 40)

        try:
            # Save user message to database
            JobQuoteChat.objects.create(
                job=job,
                message_id=f"user-test-{i}",
                role="user",
                content=test["content"],
            )

            # Generate AI response
            response = service.generate_mode_response(
                job_id=str(job.id),
                user_message=test["content"],
                mode=None,  # Let it infer the mode
            )

            # Display response
            print("Assistant response (first 500 chars):")
            print(response.content[:500])
            if len(response.content) > 500:
                print(f"... (truncated, total length: {len(response.content)} chars)")

            # Check if response contains expected elements
            if test["expected_mode"] == "CALC":
                if (
                    "items" in response.content.lower()
                    or "calculated" in response.content.lower()
                ):
                    print("✓ Response appears to contain calculations")
            elif test["expected_mode"] == "PRICE":
                if (
                    "option" in response.content.lower()
                    or "price" in response.content.lower()
                ):
                    print("✓ Response appears to contain pricing")

        except Exception as e:
            print(f"❌ Error: {e}")
            import traceback

            traceback.print_exc()

    # Show final chat history
    print(f"\n{'=' * 60}")
    print("FINAL CHAT HISTORY IN DATABASE")
    print("=" * 60)
    messages = JobQuoteChat.objects.filter(job=job).order_by("timestamp")
    for msg in messages:
        role = "User" if msg.role == "user" else "AI"
        print(f"{role}: {msg.content[:100]}...")
        if len(msg.content) > 100:
            print(f"      ... (truncated from {len(msg.content)} chars)")

    print(f"\nTotal messages in conversation: {messages.count()}")
    print("\nTest complete!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test chat conversation scenarios")
    parser.add_argument(
        "--test",
        type=str,
        choices=["conversation", "simple"],
        default="conversation",
        help="Which test to run (default: conversation)",
    )
    parser.add_argument(
        "--with-file", type=str, help="Path to file to attach (for conversation test)"
    )
    args = parser.parse_args()

    if args.test == "simple":
        test_simple_scenario()
    elif args.test == "conversation":
        test_conversation(file_path=args.with_file)
