# workflow/views/xero_view.py
import json
import logging
import time
import uuid
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseForbidden,
    JsonResponse,
    StreamingHttpResponse,
)
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST
from django.views.generic import TemplateView
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.generics import ListAPIView, RetrieveAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from xero_python.identity import IdentityApi

from apps.accounting.models import Invoice
from apps.job.models import Job
from apps.job.permissions import IsOfficeStaff
from apps.purchasing.models import PurchaseOrder
from apps.workflow.api.pagination import FiftyPerPagePagination
from apps.workflow.api.xero.active_app import (
    NoActiveXeroApp,
    get_active_app,
    get_active_client,
    wipe_tokens_and_quota,
)
from apps.workflow.api.xero.auth import (
    exchange_code_for_token,
    get_authentication_url,
    get_tenant_id_from_connections,
    get_valid_token,
    refresh_token,
)
from apps.workflow.api.xero.sync import ENTITY_CONFIGS
from apps.workflow.exceptions import AlreadyLoggedException
from apps.workflow.models import XeroError
from apps.workflow.serializers import (
    XeroAuthenticationErrorResponseSerializer,
    XeroDocumentErrorResponseSerializer,
    XeroDocumentSuccessResponseSerializer,
    XeroErrorSerializer,
    XeroPingResponseSerializer,
    XeroQuoteCreateSerializer,
    XeroSseEventSerializer,
    XeroSyncInfoResponseSerializer,
    XeroSyncStartResponseSerializer,
    XeroTriggerSyncResponseSerializer,
)
from apps.workflow.services.error_persistence import (
    persist_and_raise,
    persist_app_error,
)
from apps.workflow.services.xero_sync_service import XeroSyncService

from .xero_invoice_manager import XeroInvoiceManager

# Import the new creator classes
from .xero_po_manager import XeroPurchaseOrderManager
from .xero_quote_manager import XeroQuoteManager

logger = logging.getLogger("xero")


def _build_xero_error_payload(
    exc: Exception,
    *,
    message: str = "An unexpected server error occurred.",
    persist_context: dict | None = None,
) -> dict[str, object]:
    """
    Generate a consistent error payload and persist the exception if needed.
    """
    error_id = exc.app_error_id if isinstance(exc, AlreadyLoggedException) else None

    payload: dict[str, object] = {"success": False, "error": message}
    if error_id:
        payload["error_id"] = str(error_id)
    return payload


def _require_office_staff_html(request: HttpRequest):
    if not request.user.is_authenticated:
        logger.warning(f"Guard rejected unauthenticated request to {request.path}")
        return redirect(getattr(settings, "LOGIN_URL", "/login/"))
    if not getattr(request.user, "is_office_staff", False):
        logger.warning(f"Guard rejected non-office-staff request to {request.path}")
        return HttpResponseForbidden("Office staff only")
    return None


# Xero Authentication (Step 1: Redirect user to Xero OAuth2 login)
@csrf_exempt
def xero_authenticate(request: HttpRequest) -> HttpResponse:
    state = str(uuid.uuid4())
    request.session["oauth_state"] = state
    redirect_after_login = request.GET.get("next", "/")
    request.session["post_login_redirect"] = redirect_after_login
    authorization_url = get_authentication_url(state)
    return redirect(authorization_url)


def _build_post_xero_url(redirect_path: str) -> str:
    frontend_url = getattr(settings, "FRONT_END_URL", None)
    if not isinstance(frontend_url, str) or not frontend_url:
        return redirect_path
    if not redirect_path.startswith("/"):
        return frontend_url.rstrip("/") + "/"
    return frontend_url.rstrip("/") + redirect_path


# OAuth callback
@csrf_exempt
def xero_oauth_callback(request: HttpRequest) -> HttpResponse:
    redirect_path = request.session.pop("post_login_redirect", "/") or "/"

    error = request.GET.get("error")
    if error:
        error_description = request.GET.get("error_description", error)
        logger.info(f"Xero OAuth cancelled or denied: {error_description}")
        return redirect(
            f"{_build_post_xero_url(redirect_path)}?{urlencode({'xero_error': error_description})}"
        )

    code = request.GET.get("code")
    state = request.GET.get("state")
    session_state = request.session.get("oauth_state")
    result = exchange_code_for_token(code, state, session_state)
    if "error" in result:
        return redirect(
            f"{_build_post_xero_url(redirect_path)}?{urlencode({'xero_error': result['error']})}"
        )

    try:
        identity_api = IdentityApi(get_active_client())
        connections = identity_api.get_connections()
        if connections:
            logger.info("Available Xero Organizations after authentication:")
            for conn in connections:
                logger.info(f"Tenant ID: {conn.tenant_id}, Name: {conn.tenant_name}")
        else:
            logger.info("No Xero organizations found after authentication")
    except Exception as e:
        logger.warning(
            f"Failed to log available tenant IDs after authentication: {str(e)}"
        )

    redirect_url = _build_post_xero_url(redirect_path)
    logger.info(f"Redirecting user to frontend: {redirect_url}")
    return redirect(redirect_url)


# Refresh OAuth token and handle redirects
@csrf_exempt
def refresh_xero_token(request: HttpRequest) -> HttpResponse:
    guard = _require_office_staff_html(request)
    if guard:
        return guard
    refreshed_token = refresh_token()
    if not refreshed_token:
        return redirect("api_xero_authenticate")
    return redirect("xero_index")  # Redirect to index after refresh


# Xero connection success view
@csrf_exempt
def success_xero_connection(request: HttpRequest) -> HttpResponse:
    return render(request, "xero/success_xero_connection.html")


@csrf_exempt
def refresh_xero_data(request):
    """Refresh Xero data, handling authentication properly."""
    guard = _require_office_staff_html(request)
    if guard:
        return guard
    try:
        token = get_valid_token()
        if not token:
            logger.info("No valid token found, redirecting to Xero authentication")
            return redirect("api_xero_authenticate")
        return redirect("xero_sync_progress")
    except Exception as e:
        logger.error(f"Error while refreshing Xero data: {str(e)}")
        if "token" in str(e).lower():
            return redirect("api_xero_authenticate")
        return render(request, "general/generic_error.html", {"error_message": str(e)})


# workflow/views/xero_sync_events.py


logger = logging.getLogger("xero.events")


def generate_xero_sync_events():
    """
    SSE generator yielding JSON-encoded sync progress messages.

    Steps:
    1) Authenticate: ensure a valid Xero OAuth token is available.
    2) Emit an initial 'Starting Xero sync' event.
    3) Poll the XeroSyncService cache for new messages, streaming each one.
    4) Once no lock and no new messages, emit a final 'Sync stream ended' event.
    5) Handle unexpected errors by logging and emitting a single error event,
       then a final end-of-stream event without re-raising exceptions.
    """
    try:
        # 1) Authentication check
        if not get_valid_token():
            payload = {
                "datetime": timezone.now().isoformat(),
                "entity": "sync",
                "severity": "error",
                "message": "No valid Xero token. Please authenticate.",
                "progress": None,
            }
            yield f"data: {json.dumps(payload)}\n\n"
            return

        # 2) Starting event
        start_payload = {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "info",
            "message": "Starting Xero sync",
            "progress": 0.0,
        }
        yield f"data: {json.dumps(start_payload)}\n\n"

        # 3) Begin streaming cached messages
        task_id = XeroSyncService.get_active_task_id()
        last_index = 0

        while True:
            active_task_id = XeroSyncService.get_active_task_id()

            if task_id is None and active_task_id:
                task_id = active_task_id
                last_index = 0

            if task_id is None:
                yield ": keep-alive\n\n"
                time.sleep(0.5)
                continue

            messages = XeroSyncService.get_messages(task_id, last_index)

            # 4b) Stream each new message
            for msg in messages:
                yield f"data: {json.dumps(msg)}\n\n"
                last_index += 1

            has_active_lock = active_task_id == task_id and active_task_id is not None

            # 4a) If sync lock released and no pending messages → end
            if not has_active_lock and not messages:
                error_found = False
                error_messages = []
                all_msgs = XeroSyncService.get_messages(task_id, 0)
                for m in all_msgs:
                    if m.get("severity") == "error":
                        error_found = True
                        error_messages.append(m.get("message"))
                end_payload = {
                    "datetime": timezone.now().isoformat(),
                    "entity": "sync",
                    "severity": "info",
                    "message": "Sync stream ended",
                    "progress": 1.0,
                    "sync_status": "error" if error_found else "success",
                }
                if error_found:
                    end_payload["error_messages"] = error_messages
                logger.info(f"[SSE END PAYLOAD] {json.dumps(end_payload)}")
                yield f"data: {json.dumps(end_payload)}\n\n"
                break

            if not messages:
                yield ": keep-alive\n\n"

            # 4c) Sleep to reduce CPU load
            time.sleep(0.5)

    except Exception:
        # 5) Unexpected error
        logger.exception("Unexpected error in generate_xero_sync_events")
        error_payload = {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "error",
            "message": "Internal server error during sync.",
            "progress": None,
        }
        yield f"data: {json.dumps(error_payload)}\n\n"

        final_payload = {
            "datetime": timezone.now().isoformat(),
            "entity": "sync",
            "severity": "info",
            "message": "Sync stream ended",
            "progress": None,
        }
        yield f"data: {json.dumps(final_payload)}\n\n"


@csrf_exempt
@extend_schema(
    description="Xero Sync Event Stream",
    responses={200: XeroSseEventSerializer(many=True)},
)
@require_GET
def stream_xero_sync(request: HttpRequest) -> StreamingHttpResponse:
    """
    HTTP endpoint to serve an EventSource stream of Xero sync events.
    """
    if not request.user.is_authenticated:
        return JsonResponse(
            {"detail": "Authentication credentials were not provided."}, status=401
        )
    response = StreamingHttpResponse(
        generate_xero_sync_events(), content_type="text/event-stream"
    )
    # Prevent Django or proxies from buffering
    response["Cache-Control"] = "no-cache, no-transform"
    response["X-Accel-Buffering"] = "no"
    response["Content-Encoding"] = "identity"
    return response


def ensure_xero_authentication():
    """
    Ensure the user is authenticated with Xero and retrieves the tenant ID.
    If authentication is missing, it returns a JSON response prompting login.
    """
    token = get_valid_token()
    if not token:
        error_response = {
            "success": False,
            "redirect_to_auth": True,
            "message": "Your Xero session has expired. Please log in again.",
        }
        error_serializer = XeroAuthenticationErrorResponseSerializer(error_response)
        return JsonResponse(error_serializer.data, status=401)

    tenant_id = cache.get("xero_tenant_id")  # Use consistent cache key
    if not tenant_id:
        try:
            tenant_id = get_tenant_id_from_connections()
            cache.set("xero_tenant_id", tenant_id, timeout=1800)
        except Exception as e:
            logger.error(f"Error retrieving tenant ID: {e}")
            error_response = {
                "success": False,
                "redirect_to_auth": True,
                "message": "Unable to fetch Xero tenant ID. Please log in Xero again.",
            }
            error_serializer = XeroAuthenticationErrorResponseSerializer(error_response)
            return JsonResponse(error_serializer.data, status=401)
    return tenant_id


@csrf_exempt
@extend_schema(
    tags=["Xero"],
    request=None,
    responses={
        201: XeroDocumentSuccessResponseSerializer,
        400: XeroDocumentErrorResponseSerializer,
        404: XeroDocumentErrorResponseSerializer,
        500: XeroDocumentErrorResponseSerializer,
    },
    description="Creates an invoice in Xero for the specified job",
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOfficeStaff])
def create_xero_invoice(request: Request, job_id: uuid.UUID) -> Response:
    """Creates an Invoice in Xero for a given job."""
    tenant_id = ensure_xero_authentication()
    if isinstance(tenant_id, JsonResponse):
        # Convert JsonResponse to DRF Response
        return Response(json.loads(tenant_id.content), status=tenant_id.status_code)

    try:
        job = Job.objects.get(id=job_id)
        manager = XeroInvoiceManager(client=job.client, job=job, staff=request.user)
        result_data = manager.create_document()

        if result_data.get("success"):
            messages.success(request, "Invoice created successfully")
            serializer = XeroDocumentSuccessResponseSerializer(data=result_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            messages.error(
                request, f"Failed to create invoice: {result_data.get('error')}"
            )
            serializer = XeroDocumentErrorResponseSerializer(data=result_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data, status=status.HTTP_400_BAD_REQUEST)

    except Job.DoesNotExist:
        error_data = {"success": False, "error": f"Job with ID {job_id} not found."}
        messages.error(request, error_data["error"])
        return Response(error_data, status=status.HTTP_404_NOT_FOUND)
    except AlreadyLoggedException as exc:
        error_data = _build_xero_error_payload(exc)
        messages.error(request, "An unexpected error occurred while creating invoice.")
        return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as exc:
        try:
            persist_and_raise(exc, job_id=str(job_id))
        except AlreadyLoggedException as logged_exc:
            error_data = _build_xero_error_payload(logged_exc)
            messages.error(request, f"An unexpected error occurred: {str(exc)}")
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@extend_schema(
    tags=["Xero"],
    request=None,
    responses={
        201: XeroDocumentSuccessResponseSerializer,
        400: XeroDocumentErrorResponseSerializer,
        404: XeroDocumentErrorResponseSerializer,
        500: XeroDocumentErrorResponseSerializer,
    },
    description="Creates or updates a Purchase Order in Xero.",
    parameters=[
        OpenApiParameter(
            name="purchase_order_id",
            location=OpenApiParameter.PATH,
            type={"type": "string", "format": "uuid"},
            required=True,
        )
    ],
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOfficeStaff])
def create_xero_purchase_order(
    request: Request, purchase_order_id: uuid.UUID
) -> Response:
    """Creates or updates a Purchase Order in Xero for a given purchase order."""
    tenant_id = ensure_xero_authentication()
    if isinstance(tenant_id, JsonResponse):
        return Response(json.loads(tenant_id.content), status=tenant_id.status_code)

    try:
        purchase_order = PurchaseOrder.objects.get(id=purchase_order_id)
        logger.info(
            f"Starting Xero sync for PO {purchase_order_id}",
            extra={
                "purchase_order_id": str(purchase_order_id),
                "po_number": purchase_order.po_number,
                "supplier_id": (
                    str(purchase_order.supplier.id) if purchase_order.supplier else None
                ),
                "user_id": (
                    str(request.user.id) if request.user.is_authenticated else None
                ),
            },
        )
        manager = XeroPurchaseOrderManager(
            purchase_order=purchase_order, staff=request.user
        )
        result_data = manager.sync_to_xero()

        logger.info(
            f"Manager returned result for PO {purchase_order_id}: success={result_data.get('success')}",
            extra={
                "purchase_order_id": str(purchase_order_id),
                "result_data": result_data,
            },
        )

        # Handle unhappy case first
        if not result_data.get("success"):
            error_msg = result_data.get("error", "Unknown error")
            error_type = result_data.get("error_type", "unknown")
            status_code = result_data.get("status", 400)

            try:
                persist_and_raise(
                    ValueError(error_msg),
                    user_id=(
                        str(request.user.id) if request.user.is_authenticated else None
                    ),
                    additional_context={
                        "purchase_order_id": str(purchase_order_id),
                        "error_type": error_type,
                        "result_data": result_data,
                        "request_path": request.path,
                        "request_method": request.method,
                    },
                )
            except AlreadyLoggedException as logged_exc:
                messages.error(request, f"Failed to sync Purchase Order: {error_msg}")
                logger.warning(
                    f"Failed to sync PO {purchase_order_id}: {error_msg}",
                    extra={
                        "purchase_order_id": str(purchase_order_id),
                        "error_message": error_msg,
                        "error_type": error_type,
                        "result_data": result_data,
                    },
                )
                serializer = XeroDocumentErrorResponseSerializer(data=result_data)
                serializer.is_valid(raise_exception=True)
                payload = serializer.data
                if logged_exc.app_error_id:
                    payload["error_id"] = str(logged_exc.app_error_id)
                return Response(payload, status=status_code)

        # Handle happy case
        messages.success(request, "Purchase Order synced successfully with Xero.")
        logger.info(
            f"Successfully synced PO {purchase_order_id} to Xero",
            extra={
                "purchase_order_id": str(purchase_order_id),
                "xero_id": result_data.get("xero_id"),
                "online_url": result_data.get("online_url"),
            },
        )
        serializer = XeroDocumentSuccessResponseSerializer(data=result_data)
        serializer.is_valid(raise_exception=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    except PurchaseOrder.DoesNotExist:
        logger.warning(
            f"Purchase Order not found: {purchase_order_id}",
            extra={
                "purchase_order_id": str(purchase_order_id),
                "user_id": (
                    str(request.user.id) if request.user.is_authenticated else None
                ),
            },
        )
        error_data = {
            "success": False,
            "error": f"Purchase Order with ID {purchase_order_id} not found.",
        }
        messages.error(request, error_data["error"])
        return Response(error_data, status=status.HTTP_404_NOT_FOUND)
    except AlreadyLoggedException as exc:
        logger.exception(
            f"Unexpected error in create_xero_purchase_order view for PO {purchase_order_id}",
            extra={
                "purchase_order_id": str(purchase_order_id),
                "user_id": (
                    str(request.user.id) if request.user.is_authenticated else None
                ),
                "error_type": type(exc.original).__name__,
                "error_message": str(exc.original),
            },
        )
        error_data = _build_xero_error_payload(exc)
        messages.error(request, "An unexpected error occurred while syncing PO.")
        return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as exc:
        logger.exception(
            f"Unexpected error in create_xero_purchase_order view for PO {purchase_order_id}",
            extra={
                "purchase_order_id": str(purchase_order_id),
                "user_id": (
                    str(request.user.id) if request.user.is_authenticated else None
                ),
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        try:
            persist_and_raise(
                exc,
                user_id=str(request.user.id) if request.user.is_authenticated else None,
                additional_context={
                    "purchase_order_id": str(purchase_order_id),
                    "request_path": request.path,
                    "request_method": request.method,
                },
            )
        except AlreadyLoggedException as logged_exc:
            error_data = _build_xero_error_payload(logged_exc)
            messages.error(request, f"An unexpected error occurred: {str(exc)}")
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@extend_schema(
    tags=["Xero"],
    request=XeroQuoteCreateSerializer,
    responses={
        201: XeroDocumentSuccessResponseSerializer,
        400: XeroDocumentErrorResponseSerializer,
        404: XeroDocumentErrorResponseSerializer,
        500: XeroDocumentErrorResponseSerializer,
    },
    description="Creates a quote in Xero for the specified job",
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOfficeStaff])
def create_xero_quote(request: Request, job_id: uuid.UUID) -> Response:
    """Creates a quote in Xero for a given job."""
    tenant_id = ensure_xero_authentication()
    if isinstance(tenant_id, JsonResponse):
        return Response(json.loads(tenant_id.content), status=tenant_id.status_code)

    # Validate request body
    request_serializer = XeroQuoteCreateSerializer(data=request.data)
    if not request_serializer.is_valid():
        error_data = {
            "success": False,
            "error": "Invalid request data.",
            "messages": [str(request_serializer.errors)],
        }
        return Response(error_data, status=status.HTTP_400_BAD_REQUEST)

    breakdown = request_serializer.validated_data["breakdown"]

    try:
        job = Job.objects.get(id=job_id)
        manager = XeroQuoteManager(client=job.client, job=job, staff=request.user)
        result_data = manager.create_document(breakdown=breakdown)

        if result_data.get("success"):
            messages.success(request, "Quote created successfully.")
            serializer = XeroDocumentSuccessResponseSerializer(data=result_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            messages.error(
                request, f"Failed to create quote: {result_data.get('error')}"
            )
            serializer = XeroDocumentErrorResponseSerializer(data=result_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data, status=status.HTTP_400_BAD_REQUEST)

    except Job.DoesNotExist:
        error_data = {"success": False, "error": f"Job with ID {job_id} not found."}
        return Response(error_data, status=status.HTTP_404_NOT_FOUND)
    except AlreadyLoggedException as exc:
        error_data = _build_xero_error_payload(exc)
        return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as exc:
        try:
            persist_and_raise(exc, job_id=str(job_id))
        except AlreadyLoggedException as logged_exc:
            error_data = _build_xero_error_payload(logged_exc)
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@extend_schema(
    tags=["Xero"],
    request=None,
    responses={
        200: XeroDocumentSuccessResponseSerializer,
        400: XeroDocumentErrorResponseSerializer,
        404: XeroDocumentErrorResponseSerializer,
        500: XeroDocumentErrorResponseSerializer,
    },
    description="Deletes a specific invoice in Xero for a given job, identified by its Xero ID.",
    parameters=[
        OpenApiParameter(
            name="job_id", location=OpenApiParameter.PATH, required=True, type=str
        ),
        OpenApiParameter(
            name="xero_invoice_id",
            location=OpenApiParameter.QUERY,
            required=True,
            type=str,
        ),
    ],
)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated, IsOfficeStaff])
def delete_xero_invoice(request: Request, job_id: uuid.UUID) -> Response:
    """Deletes a specific invoice in Xero for a given job, identified by its Xero ID."""
    tenant_id = ensure_xero_authentication()
    if isinstance(tenant_id, JsonResponse):
        return Response(json.loads(tenant_id.content), status=tenant_id.status_code)

    xero_invoice_id = request.query_params.get("xero_invoice_id")
    if not xero_invoice_id:
        error_data = {
            "success": False,
            "error": "xero_invoice_id is a required query parameter.",
        }
        return Response(error_data, status=status.HTTP_400_BAD_REQUEST)

    try:
        job = Job.objects.get(id=job_id)
        invoice = Invoice.objects.get(xero_id=xero_invoice_id, job=job)
        manager = XeroInvoiceManager(
            client=job.client,
            job=job,
            staff=request.user,
            xero_invoice_id=invoice.xero_id,
        )
        result_data: dict = manager.delete_document()

        if result_data.get("success"):
            messages.success(request, "Invoice deleted successfully.")
            serializer = XeroDocumentSuccessResponseSerializer(data=result_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            messages.error(
                request, f"Failed to delete invoice: {result_data.get('error')}"
            )
            serializer = XeroDocumentErrorResponseSerializer(data=result_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data, status=status.HTTP_400_BAD_REQUEST)

    except Job.DoesNotExist:
        error_data = {"success": False, "error": f"Job with ID {job_id} not found."}
        return Response(error_data, status=status.HTTP_404_NOT_FOUND)
    except Invoice.DoesNotExist:
        error_data = {
            "success": False,
            "error": f"Invoice with Xero ID {xero_invoice_id} not found for this job.",
        }
        return Response(error_data, status=status.HTTP_404_NOT_FOUND)
    except AlreadyLoggedException as exc:
        error_data = _build_xero_error_payload(exc)
        return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as exc:
        try:
            persist_and_raise(exc, job_id=str(job_id))
        except AlreadyLoggedException as logged_exc:
            error_data = _build_xero_error_payload(logged_exc)
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@extend_schema(
    tags=["Xero"],
    request=None,
    responses={
        200: XeroDocumentSuccessResponseSerializer,
        404: XeroDocumentErrorResponseSerializer,
        500: XeroDocumentErrorResponseSerializer,
    },
    description="Deletes a quote in Xero for the specified job",
)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated, IsOfficeStaff])
def delete_xero_quote(request: Request, job_id: uuid.UUID) -> Response:
    """Deletes a quote in Xero for a given job."""
    tenant_id = ensure_xero_authentication()
    if isinstance(tenant_id, JsonResponse):
        return Response(json.loads(tenant_id.content), status=tenant_id.status_code)

    try:
        job = Job.objects.get(id=job_id)
        manager = XeroQuoteManager(client=job.client, job=job, staff=request.user)
        result_data: dict = manager.delete_document()

        if result_data.get("success"):
            messages.success(request, "Quote deleted successfully.")
            serializer = XeroDocumentSuccessResponseSerializer(data=result_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            messages.error(
                request, f"Failed to delete quote: {result_data.get('error')}"
            )
            serializer = XeroDocumentErrorResponseSerializer(data=result_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data, status=status.HTTP_400_BAD_REQUEST)

    except Job.DoesNotExist:
        error_data = {"success": False, "error": f"Job with ID {job_id} not found."}
        messages.error(request, error_data["error"])
        return Response(error_data, status=status.HTTP_404_NOT_FOUND)
    except AlreadyLoggedException as exc:
        logger.exception(f"Error in delete_xero_quote view for job {job_id}")
        error_data = _build_xero_error_payload(exc)
        messages.error(request, "An unexpected error occurred while deleting quote.")
        return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as exc:
        logger.exception(f"Error in delete_xero_quote view for job {job_id}")
        try:
            persist_and_raise(exc, job_id=str(job_id))
        except AlreadyLoggedException as logged_exc:
            error_data = _build_xero_error_payload(logged_exc)
            messages.error(request, f"An unexpected error occurred: {str(exc)}")
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@csrf_exempt
@extend_schema(
    tags=["Xero"],
    request=None,
    responses={
        200: XeroDocumentSuccessResponseSerializer,
        404: XeroDocumentErrorResponseSerializer,
        500: XeroDocumentErrorResponseSerializer,
    },
    description="Deletes a purchase order in Xero for the specified purchase order",
)
@api_view(["DELETE"])
@permission_classes([IsAuthenticated, IsOfficeStaff])
def delete_xero_purchase_order(
    request: Request, purchase_order_id: uuid.UUID
) -> Response:
    """Deletes a Purchase Order in Xero."""
    tenant_id = ensure_xero_authentication()
    if isinstance(tenant_id, JsonResponse):
        return Response(json.loads(tenant_id.content), status=tenant_id.status_code)

    try:
        purchase_order = PurchaseOrder.objects.get(id=purchase_order_id)
        manager = XeroPurchaseOrderManager(
            purchase_order=purchase_order, staff=request.user
        )
        result_data = manager.delete_document()

        if result_data.get("success"):
            messages.success(request, "Purchase Order deleted successfully.")
            serializer = XeroDocumentSuccessResponseSerializer(data=result_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        else:
            messages.error(
                request, f"Failed to delete Purchase Order: {result_data.get('error')}"
            )
            serializer = XeroDocumentErrorResponseSerializer(data=result_data)
            serializer.is_valid(raise_exception=True)
            return Response(serializer.data, status=status.HTTP_400_BAD_REQUEST)

    except PurchaseOrder.DoesNotExist:
        error_data = {
            "success": False,
            "error": f"Purchase Order with ID {purchase_order_id} not found.",
        }
        messages.error(request, error_data["error"])
        return Response(error_data, status=status.HTTP_404_NOT_FOUND)
    except AlreadyLoggedException as exc:
        logger.exception(
            f"Error in delete_xero_purchase_order view for PO {purchase_order_id}"
        )
        error_data = _build_xero_error_payload(exc)
        messages.error(request, "An unexpected error occurred while deleting PO.")
        return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    except Exception as exc:
        logger.exception(
            f"Error in delete_xero_purchase_order view for PO {purchase_order_id}"
        )
        try:
            persist_and_raise(
                exc,
                additional_context={"purchase_order_id": str(purchase_order_id)},
            )
        except AlreadyLoggedException as logged_exc:
            error_data = _build_xero_error_payload(logged_exc)
            messages.error(request, f"An unexpected error occurred: {str(exc)}")
            return Response(error_data, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=["Xero"],
    description="Disconnects from Xero by clearing the token from cache and database.",
    request=None,
    responses={200: XeroPingResponseSerializer},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOfficeStaff])
def xero_disconnect(request):
    """Disconnect from Xero by clearing tokens on the active XeroApp.

    The row itself stays so the user can re-authorise without re-entering
    credentials. Inactive rows (e.g. a backup app) are untouched.
    """
    try:
        cache.delete("xero_tenant_id")
        try:
            active = get_active_app()
        except NoActiveXeroApp:
            logger.info("xero_disconnect: no active XeroApp; nothing to do")
            return Response({"connected": False}, status=status.HTTP_200_OK)
        wipe_tokens_and_quota(active)
        logger.info(f"Disconnected XeroApp {active.id} ({active.label})")
        return Response({"connected": False}, status=status.HTTP_200_OK)
    except AlreadyLoggedException:
        raise
    except Exception as exc:
        persist_app_error(exc)
        logger.error(f"Error disconnecting from Xero: {str(exc)}")
        return Response(
            {"error": "Failed to disconnect from Xero"},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class XeroIndexView(TemplateView):
    """Note this page is currently inaccessible. We are using a dropdown menu instead."""

    template_name = "xero_index.html"

    def dispatch(self, request, *args, **kwargs):
        guard = _require_office_staff_html(request)
        if guard:
            return guard
        return super().dispatch(request, *args, **kwargs)


@csrf_exempt
def xero_sync_progress_page(request):
    """Render the Xero sync progress page."""
    guard = _require_office_staff_html(request)
    if guard:
        return guard
    try:
        token = get_valid_token()
        if not token:
            logger.info("No valid token found, redirecting to Xero authentication")
            return redirect("api_xero_authenticate")

        # Build entity list from ENTITY_CONFIGS (the single source of truth)
        xero_entities = list(ENTITY_CONFIGS.keys())

        return render(
            request, "xero/xero_sync_progress.html", {"XERO_ENTITIES": xero_entities}
        )
    except Exception as e:
        logger.error(f"Error accessing sync progress page: {str(e)}")
        if "token" in str(e).lower():
            return redirect("api_xero_authenticate")
        return render(request, "general/generic_error.html", {"error_message": str(e)})


def _get_last_sync_time(model):
    """Get the last sync time for a model, or None if no records exist."""
    if not model.objects.exists():
        return None
    latest = model.objects.order_by("-xero_last_synced").first()
    return latest.xero_last_synced if latest else None


@extend_schema(
    tags=["Xero"],
    description="Get current sync status and last sync times for all entities.",
    responses={200: XeroSyncInfoResponseSerializer},
)
@api_view(["GET"])
def get_xero_sync_info(request):
    """Get current sync status and last sync times for all entities in ENTITY_CONFIGS."""
    token = get_valid_token()
    if not token:
        return Response(
            {
                "error": "No valid Xero token. Please authenticate.",
                "redirect_to_auth": True,
            },
            status=status.HTTP_401_UNAUTHORIZED,
        )

    try:
        # Build last_syncs dynamically from ENTITY_CONFIGS
        last_syncs = {}
        for entity_key, config in ENTITY_CONFIGS.items():
            model = config[2]  # Model is at index 2 in the config tuple
            last_syncs[entity_key] = _get_last_sync_time(model)

        sync_range = "Syncing data since last successful sync"
        sync_in_progress = cache.get("xero_sync_lock", False)

        response_data = {
            "last_syncs": last_syncs,
            "sync_range": sync_range,
            "sync_in_progress": sync_in_progress,
        }
        return Response(response_data, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error getting sync info: {str(e)}")
        persist_app_error(e)
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@extend_schema(
    tags=["Xero"],
    description="Start a Xero sync as a background task.",
    request=None,
    responses={200: XeroSyncStartResponseSerializer},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated, IsOfficeStaff])
def start_xero_sync(request):
    """
    View function to start a Xero sync as a background task.
    """
    try:
        token = get_valid_token()
        if not token:
            error_response = {"error": "No valid token. Please authenticate."}
            error_serializer = XeroSyncStartResponseSerializer(error_response)
            return JsonResponse(error_serializer.data, status=401)

        # Start sync using the service
        task_id, is_new = XeroSyncService.start_sync()

        if not task_id:
            error_response = {
                "status": "error",
                "message": "Failed to start sync. The scheduler may not be running or a sync is already in progress.",
            }
            error_serializer = XeroSyncStartResponseSerializer(error_response)
            return JsonResponse(error_serializer.data, status=500)

        message = "Started new Xero sync" if is_new else "A sync is already running"
        response_data = {"status": "success", "message": message, "task_id": task_id}

        response_serializer = XeroSyncStartResponseSerializer(response_data)
        return JsonResponse(response_serializer.data)
    except Exception as e:
        logger.error(f"Error starting Xero sync: {str(e)}")
        error_response = {"error": str(e)}
        error_serializer = XeroSyncStartResponseSerializer(error_response)
        return JsonResponse(error_serializer.data, status=500)


@csrf_exempt
@require_POST
def trigger_xero_sync(request):
    """
    Manual “Sync now” endpoint. Returns the task_id so the frontend
    can connect to the same SSE stream.
    """
    # Ensure user is authenticated with Xero
    tenant = ensure_xero_authentication()
    if isinstance(tenant, JsonResponse):
        return tenant

    task_id, started = XeroSyncService.start_sync()
    if not task_id:
        error_response = {"success": False, "message": "Unable to start sync."}
        error_serializer = XeroTriggerSyncResponseSerializer(error_response)
        return JsonResponse(error_serializer.data, status=400)

    response_data = {"success": True, "task_id": task_id, "started": started}
    response_serializer = XeroTriggerSyncResponseSerializer(response_data)
    return JsonResponse(response_serializer.data)


@extend_schema(
    tags=["Xero"],
    description="Check if the user is authenticated with Xero.",
    responses={200: XeroPingResponseSerializer},
)
@api_view(["GET"])
def xero_ping(request):
    """
    Simple endpoint to check if the user is authenticated with Xero.
    Returns {"connected": true} or {"connected": false}.
    Always returns HTTP 200 for frontend simplicity.
    """
    try:
        token = get_valid_token()
        is_connected = bool(token)
        logger.info(f"Xero ping: connected={is_connected}")
        return Response({"connected": is_connected}, status=status.HTTP_200_OK)
    except Exception as e:
        logger.error(f"Error in xero_ping: {str(e)}")
        return Response({"connected": False}, status=status.HTTP_200_OK)


class XeroErrorListAPIView(ListAPIView):
    """
    API view for listing Xero synchronization errors.

    Returns a paginated list of all XeroError records ordered by timestamp
    (most recent first). Useful for monitoring and debugging Xero integration
    issues.

    Endpoint: /api/xero/errors/
    """

    queryset = XeroError.objects.all().order_by("-timestamp")
    serializer_class = XeroErrorSerializer
    pagination_class = FiftyPerPagePagination
    permission_classes = [IsAuthenticated, IsOfficeStaff]


class XeroErrorDetailAPIView(RetrieveAPIView):
    """
    API view for retrieving a single Xero synchronization error.

    Returns detailed information about a specific XeroError record
    including error message, context, and timestamp. Used for investigating
    specific Xero integration failures.

    Endpoint: /api/xero/errors/<id>/
    """

    queryset = XeroError.objects.all()
    serializer_class = XeroErrorSerializer
    permission_classes = [IsAuthenticated, IsOfficeStaff]
