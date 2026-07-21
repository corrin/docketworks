"""
Job Quote Chat REST Views

REST API endpoints for managing chat conversations linked to jobs.
Follows the same pattern as other job REST views.
"""

import logging
import traceback

from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ParseError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.mixins import JobLookupMixin
from apps.job.models import Job, JobQuoteChat
from apps.job.permissions import IsStaffUser
from apps.job.serializers import (
    JobQuoteChatDeleteResponseSerializer,
    JobQuoteChatHistoryResponseSerializer,
    JobQuoteChatInteractionSuccessResponseSerializer,
    JobQuoteChatSerializer,
    JobQuoteChatUpdateResponseSerializer,
    JobQuoteChatUpdateSerializer,
)
from apps.job.serializers.job_quote_chat_serializer import JobQuoteChatCreateSerializer
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


class BaseJobQuoteChatView(APIView):
    """
    Base view for Job Quote Chat REST operations.
    """

    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsStaffUser()]

    @method_decorator(csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    def get_job_or_404(self, job_id):
        """Get job by ID or raise Job.DoesNotExist."""
        return Job.objects.get(id=job_id)

    def get_message_or_404(self, job, message_id):
        """Get message by job and message_id or raise JobQuoteChat.DoesNotExist."""
        return JobQuoteChat.objects.get(job=job, message_id=message_id)

    def handle_error(self, error: Exception) -> Response:
        """Handle errors and return appropriate response using match-case.

        Persists here because this method returns a Response rather than
        re-raising, so the exception never reaches the DRF boundary that
        would otherwise record it.
        """
        persist_app_error(error)

        match error:
            case ParseError():
                return Response(
                    {"success": False, "error": str(error)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            case ValueError():
                return Response(
                    {"success": False, "error": str(error)},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            case Job.DoesNotExist():
                return Response(
                    {
                        "success": False,
                        "error": "Job not found",
                        "code": "JOB_NOT_FOUND",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
            case JobQuoteChat.DoesNotExist():
                return Response(
                    {
                        "success": False,
                        "error": "Message not found",
                        "code": "MESSAGE_NOT_FOUND",
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )
            case _:
                logger.exception(f"Unhandled error in quote chat API: {error}")
                return Response(
                    {"success": False, "error": "Internal server error"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )


@method_decorator(csrf_exempt, name="dispatch")
class JobQuoteChatHistoryView(JobLookupMixin, BaseJobQuoteChatView):
    """
    REST view for getting and managing chat history for a job.

    GET: Load all chat messages for a specific job
    POST: Save a new chat message (user or assistant)
    DELETE: Clear all chat history for a job
    """

    def get_serializer_class(self):
        """Return appropriate serializer class based on request method."""
        if self.request.method == "POST":
            return JobQuoteChatCreateSerializer
        elif self.request.method == "GET":
            return JobQuoteChatHistoryResponseSerializer
        elif self.request.method == "DELETE":
            return JobQuoteChatDeleteResponseSerializer
        return JobQuoteChatHistoryResponseSerializer

    def get(self, request, job_id):
        """
        Load all chat messages for a specific job.

        Response format matches job_quote_chat_plan.md specification.
        """
        try:
            # Get job using utility method
            job = self.get_job_or_404(job_id)

            # Check if job exists
            job, error_response = self.get_job_or_404_response(error_format="api")
            if error_response:
                return error_response

            # Get all chat messages for this job, ordered by timestamp
            messages = JobQuoteChat.objects.filter(job=job).order_by("timestamp")

            # Format messages according to the API spec
            formatted_messages = []
            for message in messages:
                formatted_messages.append(
                    {
                        "message_id": message.message_id,
                        "role": message.role,
                        "content": message.content,
                        "timestamp": message.timestamp.isoformat(),
                        "metadata": message.metadata,
                    }
                )

            # Serialize the response
            response_data = {
                "success": True,
                "data": {"job_id": str(job.id), "messages": formatted_messages},
            }

            serializer = JobQuoteChatHistoryResponseSerializer(response_data)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return self.handle_error(e)

    @extend_schema(
        request=JobQuoteChatCreateSerializer,
        responses={
            201: JobQuoteChatInteractionSuccessResponseSerializer,
        },
        summary="Save a new chat message",
        description="Save a new chat message (user or assistant) for a job",
    )
    def post(self, request, job_id):
        """
        Save a new chat message (user or assistant).

        Expected JSON:
        {
            "message_id": "user-1234567892",
            "role": "user",
            "content": "Actually, make that 5 boxes instead",
            "metadata": {}
        }
        """
        try:
            # Log incoming request data
            logger.info(f"Quote chat POST - Received data: {request.data}")
            logger.info(f"Quote chat POST - Job ID: {job_id}")
            logger.info(f"Quote chat POST - Content type: {request.content_type}")

            # Get job using utility method
            job = self.get_job_or_404(job_id)

            # Check if job exists
            job, error_response = self.get_job_or_404_response(error_format="api")
            if error_response:
                logger.warning(f"Quote chat POST - Job not found: {job_id}")
                return error_response

            # Validate data using serializer
            serializer = JobQuoteChatCreateSerializer(data=request.data)

            if not serializer.is_valid():
                logger.error(
                    f"Quote chat POST - Validation errors: {serializer.errors}"
                )
                return Response(
                    {
                        "success": False,
                        "error": "Validation error",
                        "details": serializer.errors,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            logger.info(
                f"Quote chat POST - Validated data: {serializer.validated_data}"
            )

            # Create the message with job relationship
            message = serializer.save(job=job)

            # Log what was saved to database
            logger.info(f"Quote chat POST - Saved to database: id={message.id}")
            logger.info(f"Quote chat POST - Saved content: '{message.content}'")
            logger.info(f"Quote chat POST - Saved role: '{message.role}'")
            logger.info(f"Quote chat POST - Saved message_id: '{message.message_id}'")
            logger.info(f"Quote chat POST - Saved metadata: {message.metadata}")

            # Serialize the full message for response
            message_serializer = JobQuoteChatSerializer(message)
            logger.info(
                f"Quote chat POST - Serialized message data: {message_serializer.data}"
            )

            # Serialize the response
            response_data = {
                "success": True,
                "data": message_serializer.data,
            }

            response_serializer = JobQuoteChatInteractionSuccessResponseSerializer(
                response_data
            )

            # Log final response data
            logger.info(
                f"Quote chat POST - Final response data: {response_serializer.data}"
            )
            logger.info(
                f"Quote chat POST - Response content field: '{response_serializer.data.get('data', {}).get('content', 'MISSING')}'"
            )

            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Quote chat POST - Exception occurred: {str(e)}")
            logger.error(f"Quote chat POST - Exception type: {type(e).__name__}")
            logger.error(f"Quote chat POST - Traceback: {traceback.format_exc()}")
            return self.handle_error(e)

    @extend_schema(operation_id="quote_chat_delete_all")
    def delete(self, request, job_id):
        """
        Delete all chat messages for a job (start fresh).
        """
        try:
            # Get job using utility method
            job = self.get_job_or_404(job_id)

            # Check if job exists
            job, error_response = self.get_job_or_404_response(error_format="api")
            if error_response:
                return error_response

            # Delete all messages for this job
            deleted_count, _ = JobQuoteChat.objects.filter(job=job).delete()

            # Serialize the response
            response_data = {"success": True, "data": {"deleted_count": deleted_count}}

            serializer = JobQuoteChatDeleteResponseSerializer(response_data)
            return Response(serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return self.handle_error(e)


@method_decorator(csrf_exempt, name="dispatch")
class JobQuoteChatMessageView(JobLookupMixin, BaseJobQuoteChatView):
    """
    REST view for updating individual chat messages.

    PATCH: Update an existing message (useful for streaming responses)
    """

    serializer_class = JobQuoteChatUpdateSerializer

    def patch(self, request, job_id, message_id):
        """
        Update an existing message (useful for streaming responses).

        Expected JSON:
        {
            "content": "Updated message content",
            "metadata": {"final": true}
        }
        """
        try:
            # Get job and message using utility methods
            job = self.get_job_or_404(job_id)
            message = self.get_message_or_404(job, message_id)

            # Check if job exists
            job, error_response = self.get_job_or_404_response(error_format="api")
            if error_response:
                return error_response

            # Validate and update using serializer
            serializer = JobQuoteChatUpdateSerializer(
                message, data=request.data, partial=True
            )
            serializer.is_valid(raise_exception=True)
            updated_message = serializer.save()

            # Serialize the response
            response_data = {
                "success": True,
                "data": {
                    "message_id": updated_message.message_id,
                    "content": updated_message.content,
                    "metadata": updated_message.metadata,
                    "timestamp": updated_message.timestamp.isoformat(),
                },
            }

            response_serializer = JobQuoteChatUpdateResponseSerializer(response_data)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            return self.handle_error(e)

    @extend_schema(operation_id="quote_chat_delete_one")
    def delete(self, request, job_id, message_id):
        """
        Delete an individual chat message.
        """
        try:
            # Get job and message using utility methods
            job = self.get_job_or_404(job_id)
            message = self.get_message_or_404(job, message_id)

            # Check if job exists
            job, error_response = self.get_job_or_404_response(error_format="api")
            if error_response:
                return error_response

            # Delete the message
            message.delete()

            return Response(status=status.HTTP_204_NO_CONTENT)

        except Exception as e:
            return self.handle_error(e)
