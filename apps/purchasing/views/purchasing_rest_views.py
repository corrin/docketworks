"""REST views for purchasing module."""

import logging
import traceback

from django.core.exceptions import ValidationError
from django.db.models import OuterRef, Subquery
from django.http import FileResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.job.models import Job
from apps.purchasing.etag import generate_po_etag, normalize_etag
from apps.purchasing.models import PurchaseOrder, PurchaseOrderEvent, Stock
from apps.purchasing.serializers import (
    AllJobsResponseSerializer,
    AllocationDeleteResponseSerializer,
    AllocationDeleteSerializer,
    AllocationDetailsResponseSerializer,
    DeliveryReceiptResponseSerializer,
    DeliveryReceiptSerializer,
    ProductMappingListResponseSerializer,
    ProductMappingSerializer,
    ProductMappingValidateResponseSerializer,
    ProductMappingValidateSerializer,
    PurchaseOrderAllocationsResponseSerializer,
    PurchaseOrderCreateResponseSerializer,
    PurchaseOrderCreateSerializer,
    PurchaseOrderDetailSerializer,
    PurchaseOrderEmailResponseSerializer,
    PurchaseOrderEmailSerializer,
    PurchaseOrderEventCreateResponseSerializer,
    PurchaseOrderEventCreateSerializer,
    PurchaseOrderEventsResponseSerializer,
    PurchaseOrderLastNumberResponseSerializer,
    PurchaseOrderListSerializer,
    PurchaseOrderPDFResponseSerializer,
    PurchaseOrderUpdateResponseSerializer,
    PurchaseOrderUpdateSerializer,
    PurchasingErrorResponseSerializer,
    PurchasingJobsResponseSerializer,
    SupplierPriceStatusResponseSerializer,
    XeroItemListResponseSerializer,
)
from apps.purchasing.services.allocation_service import (
    AllocationDeletionError,
    AllocationService,
)
from apps.purchasing.services.delivery_receipt_service import process_delivery_receipt
from apps.purchasing.services.purchase_order_email_service import (
    create_purchase_order_email,
)
from apps.purchasing.services.purchase_order_pdf_service import (
    create_purchase_order_pdf,
)
from apps.purchasing.services.purchasing_rest_service import (
    PreconditionFailedError,
    PurchasingRestService,
)
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


class PurchaseOrderETagMixin:
    """Shared helpers for purchase order ETag handling."""

    def _normalize_etag(self, value):
        return normalize_etag(value)

    def _get_if_match(self, request):
        header = request.headers.get("If-Match") or request.META.get("HTTP_IF_MATCH")
        return self._normalize_etag(header) if header else None

    def _get_if_none_match(self, request):
        header = request.headers.get("If-None-Match") or request.META.get(
            "HTTP_IF_NONE_MATCH"
        )
        return self._normalize_etag(header) if header else None

    def _precondition_required_response(self):
        error = {"error": "Missing If-Match header (precondition required)"}
        return Response(
            error,
            status=status.HTTP_428_PRECONDITION_REQUIRED,
        )

    def _set_etag(self, response, etag: str):
        if etag:
            response["ETag"] = etag
        return response


class SupplierPriceStatusAPIView(APIView):
    """Return latest price upload status per supplier.

    Minimal-impact: read-only query over existing Client and SupplierPriceList
    models. No migrations required.
    """

    serializer_class = SupplierPriceStatusResponseSerializer

    @extend_schema(
        operation_id="getSupplierPriceStatus",
        responses=SupplierPriceStatusResponseSerializer,
    )
    def get(self, request):
        try:
            from apps.client.models import Client
            from apps.quoting.models import SupplierPriceList

            # Subquery to get the latest upload per supplier
            latest_pl = SupplierPriceList.objects.filter(
                supplier_id=OuterRef("pk")
            ).order_by("-uploaded_at")

            suppliers = (
                Client.objects.filter(
                    id__in=SupplierPriceList.objects.values("supplier_id").distinct()
                )
                .annotate(
                    last_uploaded_at=Subquery(latest_pl.values("uploaded_at")[:1]),
                    last_file_name=Subquery(latest_pl.values("file_name")[:1]),
                )
                .order_by("name")
            )

            # Build response rows, including counts and change estimate (no migrations)
            items = []
            from apps.quoting.models import SupplierProduct

            for s in suppliers:
                # Find latest and previous price lists for this supplier
                pls = (
                    SupplierPriceList.objects.filter(supplier_id=s.id)
                    .order_by("-uploaded_at")
                    .values_list("id", "file_name", "uploaded_at")
                )
                total_products = None
                changes_last_update = None
                if pls:
                    latest_id, latest_file, latest_dt = pls[0]
                    # Count all supplier products linked to this supplier (across price lists)
                    total_products = SupplierProduct.objects.filter(
                        supplier_id=s.id
                    ).count()
                    if len(pls) > 1:
                        prev_id, _, _ = pls[1]
                        latest_keys = set(
                            SupplierProduct.objects.filter(
                                price_list_id=latest_id
                            ).values_list("item_no", "variant_id")
                        )
                        prev_keys = set(
                            SupplierProduct.objects.filter(
                                price_list_id=prev_id
                            ).values_list("item_no", "variant_id")
                        )
                        additions = len(latest_keys - prev_keys)
                        removals = len(prev_keys - latest_keys)
                        changes_last_update = additions + removals

                items.append(
                    {
                        "supplier_id": s.id,
                        "supplier_name": s.name,
                        "last_uploaded_at": s.last_uploaded_at,
                        "file_name": s.last_file_name,
                        "total_products": total_products,
                        "changes_last_update": changes_last_update,
                    }
                )

            resp = {"items": items, "total_count": len(items)}
            serializer = self.serializer_class(resp)
            return Response(serializer.data)
        except Exception as e:
            logger.error(f"Error computing supplier price status: {e}")
            return Response(
                {"error": "Failed to fetch supplier price status"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AllJobsAPIView(APIView):
    """
    API endpoint to get all jobs with stock holding job flag.

    This endpoint is specifically for purchasing contexts like delivery receipt
    and stock allocation where we need all jobs but want to identify which one
    is the stock holding job.
    """

    serializer_class = AllJobsResponseSerializer

    def get(self, request):
        """Get all jobs with stock holding job flag."""
        try:
            # Get the stock holding job using the existing method
            stock_holding_job = Stock.get_stock_holding_job()

            # Get active jobs for purchasing (archived jobs don't need POs)
            jobs = (
                Job.objects.exclude(status="archived")
                .select_related("client")
                .order_by("job_number")
            )

            # Add stock holding flag to each job
            for job in jobs:
                job._is_stock_holding = job.id == stock_holding_job.id

            # Serialize the response
            response_data = {
                "success": True,
                "jobs": jobs,
                "stock_holding_job_id": str(stock_holding_job.id),
            }

            serializer = self.serializer_class(response_data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error fetching all jobs: {e}")
            return Response(
                {"success": False, "error": "Failed to fetch jobs", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PurchasingJobsAPIView(APIView):
    """API endpoint to get jobs for purchasing contexts (PO lines, stock allocation, etc.)."""

    serializer_class = PurchasingJobsResponseSerializer

    def get(self, request):
        """Get list of jobs suitable for purchasing operations."""
        try:
            # Get jobs that are active and can have costs allocated to them
            # Exclude jobs with status that shouldn't be available for purchasing
            excluded_statuses = ["rejected", "archived", "completed", "special"]
            jobs = (
                Job.objects.filter(
                    status__in=[
                        "quoting",
                        "accepted_quote",
                        "awaiting_materials",
                        "awaiting_staff",
                        "awaiting_site_availability",
                        "in_progress",
                        "on_hold",
                        "recently_completed",
                    ]
                )
                .exclude(status__in=excluded_statuses)
                .select_related("client")
                .prefetch_related("cost_sets")
                .order_by("job_number")
            )

            # Filter jobs that can accept cost allocations
            jobs_for_purchasing = []
            for job in jobs:
                # Jobs should be able to accept material/purchasing costs
                # Either they have cost sets or are in a state where we can create them
                if (
                    job.status
                    in [
                        "in_progress",
                        "on_hold",
                        "awaiting_materials",
                        "awaiting_staff",
                        "awaiting_site_availability",
                        "recently_completed",
                        "quoting",
                    ]
                    and job.latest_actual
                ):
                    jobs_for_purchasing.append(job)

            if not jobs_for_purchasing:
                return Response({"jobs": []})

            # Serialize jobs for purchasing context
            jobs_data = []
            for job in jobs_for_purchasing:
                actual_cost_set = job.get_latest("actual")
                jobs_data.append(
                    {
                        "id": str(job.id),
                        "job_number": job.job_number,
                        "name": job.name,
                        "client_name": job.client.name if job.client else "No Client",
                        "status": job.status,
                        "charge_out_rate": float(job.charge_out_rate or 0),
                        "cost_set_id": (
                            str(actual_cost_set.id) if actual_cost_set else None
                        ),
                        "job_display_name": f"{job.job_number} - {job.name}",
                    }
                )

            return Response(jobs_data)

        except Exception as e:
            logger.error(f"Error fetching jobs for purchasing: {e}")
            return Response(
                {"error": "Failed to fetch jobs", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class XeroItemList(APIView):
    """Return list of items from Xero."""

    serializer_class = XeroItemListResponseSerializer

    def get(self, request):
        try:
            items = PurchasingRestService.list_xero_items()
            return Response({"items": items, "total_count": len(items)})
        except Exception as e:
            logger.error("Error fetching Xero items: %s", e)
            return Response(
                {"error": "Failed to fetch Xero items"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PurchaseOrderLastNumberAPIView(APIView):
    """Return the most recent purchase order number."""

    serializer_class = PurchaseOrderLastNumberResponseSerializer

    @extend_schema(
        operation_id="getLastPurchaseOrderNumber",
        responses={
            status.HTTP_200_OK: PurchaseOrderLastNumberResponseSerializer,
            status.HTTP_500_INTERNAL_SERVER_ERROR: PurchasingErrorResponseSerializer,
        },
    )
    def get(self, request):
        try:
            last_po_number = PurchasingRestService.get_last_purchase_order_number()
            serializer = self.serializer_class({"last_po_number": last_po_number})
            return Response(serializer.data)
        except Exception as exc:
            persist_app_error(exc)
            logger.error("Error fetching last purchase order number: %s", exc)
            return Response(
                {"error": "Failed to fetch last purchase order number"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PurchaseOrderListCreateRestView(APIView):
    """
    REST API view for listing and creating purchase orders.

    GET: Returns list of purchase orders with optional status filtering
    POST: Creates new purchase order from provided data
    """

    def get_serializer_class(self):
        """Return appropriate serializer class based on request method."""
        if self.request.method == "POST":
            return PurchaseOrderCreateSerializer
        return PurchaseOrderListSerializer

    @extend_schema(
        operation_id="listPurchaseOrders",
        responses={
            status.HTTP_200_OK: PurchaseOrderListSerializer(many=True),
        },
    )
    def get(self, request):
        """Get list of purchase orders with optional status filtering."""
        status_filter = request.query_params.get("status", None)

        # Get data from service (returns list of dictionaries)
        data = PurchasingRestService.list_purchase_orders()

        if status_filter:
            # Support multiple status values separated by comma
            allowed_statuses = [s.strip() for s in status_filter.split(",")]
            data = [po for po in data if po["status"] in allowed_statuses]

        # Serialize the data from service using the serializer
        serializer = PurchaseOrderListSerializer(data, many=True)
        return Response(serializer.data)

    @extend_schema(
        operation_id="createPurchaseOrder",
        request=PurchaseOrderCreateSerializer,
        responses={
            status.HTTP_201_CREATED: PurchaseOrderCreateResponseSerializer,
            status.HTTP_400_BAD_REQUEST: PurchasingErrorResponseSerializer,
            status.HTTP_500_INTERNAL_SERVER_ERROR: PurchasingErrorResponseSerializer,
        },
    )
    def post(self, request):
        """Create new purchase order."""
        serializer = PurchaseOrderCreateSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {"error": "Invalid input data", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Create PO using service
            po = PurchasingRestService.create_purchase_order(
                serializer.validated_data, created_by=request.user
            )

            # Return response
            response_data = {
                "id": str(po.id),
                "po_number": po.po_number,
            }
            response_serializer = PurchaseOrderCreateResponseSerializer(response_data)
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error creating purchase order: {str(e)}")
            return Response(
                {"error": "Failed to create purchase order", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PurchaseOrderDetailRestView(PurchaseOrderETagMixin, APIView):
    """Returns a full PO (including lines).

    Concurrency is controlled in this endpoint (ETag/If-Match).
    """

    def get_serializer_class(self):
        """Return appropriate serializer class based on request method."""
        if self.request.method == "PATCH":
            return PurchaseOrderUpdateSerializer
        return PurchaseOrderDetailSerializer

    @extend_schema(operation_id="retrievePurchaseOrder")
    def get(self, request, po_id):
        """Get purchase order details including lines."""
        # Allow fetching PO details regardless of status (including deleted)
        # to match the list endpoint behavior and allow viewing deleted POs
        queryset = (
            PurchaseOrder.objects.all()
            .select_related("supplier")
            .prefetch_related("po_lines__job__client")
        )
        po = get_object_or_404(queryset, id=po_id)
        serializer = PurchaseOrderDetailSerializer(po)
        etag = generate_po_etag(po)
        if_none_match = self._get_if_none_match(request)
        if if_none_match and if_none_match == self._normalize_etag(etag):
            return Response(status=status.HTTP_304_NOT_MODIFIED)
        response = Response(serializer.data)
        self._set_etag(response, etag)
        return response

    def patch(self, request, po_id):
        """Update purchase order.

        Concurrency is controlled in this endpoint (ETag/If-Match).
        """
        serializer = PurchaseOrderUpdateSerializer(data=request.data)

        if not serializer.is_valid():
            return Response(
                {"error": "Invalid input data", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if_match = self._get_if_match(request)
            if not if_match:
                return self._precondition_required_response()

            # Update PO using service with optimistic concurrency
            po = PurchasingRestService.update_purchase_order(
                po_id,
                serializer.validated_data,
                expected_etag=if_match,
            )

            # Return response
            response_data = {
                "id": str(po.id),
                "status": po.status,
            }
            response_serializer = PurchaseOrderUpdateResponseSerializer(response_data)
            response = Response(response_serializer.data)
            self._set_etag(response, generate_po_etag(po))
            return response

        except PreconditionFailedError as exc:
            logger.warning(
                "ETag mismatch updating purchase order %s: %s", po_id, str(exc)
            )
            return Response(
                {"error": "Precondition failed (ETag mismatch). Reload and retry."},
                status=status.HTTP_412_PRECONDITION_FAILED,
            )

        except ValidationError as exc:
            persist_app_error(exc)
            logger.warning(
                "Validation error updating purchase order %s: %s", po_id, str(exc)
            )
            return Response(
                {"error": "Validation error", "details": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        except Exception as e:
            logger.error(f"Error updating purchase order {id}: {str(e)}")
            return Response(
                {"error": "Failed to update purchase order", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class DeliveryReceiptRestView(PurchaseOrderETagMixin, APIView):
    """
    REST API view for processing delivery receipts.

    POST: Processes delivery receipt for a purchase order with stock allocations.
    Concurrency is controlled in this endpoint (ETag/If-Match).
    """

    serializer_class = DeliveryReceiptSerializer

    @extend_schema(
        responses={
            status.HTTP_200_OK: DeliveryReceiptResponseSerializer,
            status.HTTP_400_BAD_REQUEST: DeliveryReceiptResponseSerializer,
        }
    )
    def post(self, request):
        try:
            purchase_order_id = None
            # Validate input data
            serializer = self.serializer_class(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {"error": "Invalid input data", "details": serializer.errors},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            validated_data = serializer.validated_data
            purchase_order_id = validated_data["purchase_order_id"]
            allocations = validated_data["allocations"]

            if_match = self._get_if_match(request)
            if not if_match:
                return self._precondition_required_response()

            # Process the delivery receipt with optimistic concurrency
            po = process_delivery_receipt(
                purchase_order_id,
                allocations,
                request.user,
                expected_etag=if_match,
            )

            # Return success response with refreshed ETag
            response_data = {"success": True}
            response_serializer = DeliveryReceiptResponseSerializer(response_data)
            response = Response(response_serializer.data)
            self._set_etag(response, generate_po_etag(po))
            return response

        except PreconditionFailedError as exc:
            logger.warning(
                "ETag mismatch processing delivery receipt for PO %s: %s",
                purchase_order_id,
                str(exc),
            )
            response_data = {
                "success": False,
                "error": "Precondition failed (ETag mismatch). Reload and retry.",
            }
            response_serializer = DeliveryReceiptResponseSerializer(response_data)
            return Response(
                response_serializer.data,
                status=status.HTTP_412_PRECONDITION_FAILED,
            )

        except Exception as e:
            logger.error(f"Error processing delivery receipt: {str(e)}")
            response_data = {"success": False, "error": str(e)}
            response_serializer = DeliveryReceiptResponseSerializer(response_data)
            return Response(
                response_serializer.data, status=status.HTTP_400_BAD_REQUEST
            )


class PurchaseOrderAllocationsAPIView(APIView):
    """
    API endpoint to get existing allocations for a purchase order.

    This helps show previous delivery receipt allocations when creating
    new delivery receipts for partially received orders.
    """

    serializer_class = PurchaseOrderAllocationsResponseSerializer

    def get(self, request, po_id):
        """Get existing allocations for a purchase order."""
        try:
            # Import here to avoid circular imports
            from django.db.models.fields.json import KeyTextTransform

            from apps.job.models import CostLine

            # Verify PO exists
            po = get_object_or_404(PurchaseOrder, id=po_id)
            logger.info(f"Looking for allocations for PO {po_id} ({po.po_number})")

            # Find all CostLines that reference this PO
            cost_lines = (
                CostLine.objects.annotate(
                    po_id_from_refs=KeyTextTransform("purchase_order_id", "ext_refs"),
                )
                .filter(po_id_from_refs=str(po_id))
                .select_related("cost_set__job")
            )

            # Find all Stock items that reference this PO
            stock_items = Stock.objects.filter(
                source="purchase_order",
                source_purchase_order_line__purchase_order_id=po_id,
            ).select_related("job", "source_purchase_order_line")

            logger.info(
                f"Found {cost_lines.count()} CostLines and {stock_items.count()} Stock items for PO {po_id}"
            )

            # Let's also debug what CostLines we have in total that might be related
            all_cost_lines_with_po_refs = CostLine.objects.filter(
                ext_refs__isnull=False
            ).exclude(ext_refs={})[
                :10
            ]  # Limit to first 10 for debugging

            logger.debug("Sample CostLines with ext_refs:")
            for cl in all_cost_lines_with_po_refs:
                logger.debug(f"  CostLine {cl.id}: ext_refs = {cl.ext_refs}")

            # Group allocations by PO line
            allocations_by_line = {}

            # Process CostLines (direct job allocations)
            for cost_line in cost_lines:
                # Extract purchase_order_line_id from ext_refs JSON field
                line_id = None
                if cost_line.ext_refs and isinstance(cost_line.ext_refs, dict):
                    line_id = cost_line.ext_refs.get("purchase_order_line_id")

                if line_id:
                    # Ensure line_id is always a string for consistency
                    line_id = str(line_id)
                    if line_id not in allocations_by_line:
                        allocations_by_line[line_id] = []

                    allocations_by_line[line_id].append(
                        {
                            "type": "job",
                            "job_id": str(cost_line.cost_set.job.id),
                            "job_name": cost_line.cost_set.job.name,
                            "quantity": float(cost_line.quantity),
                            "retail_rate": (
                                float(cost_line.meta.get("retail_rate", 0)) * 100
                                if cost_line.meta.get("retail_rate")
                                else 0
                            ),
                            "allocation_date": (
                                cost_line.created_at.isoformat()
                                if hasattr(cost_line, "created_at")
                                else None
                            ),
                            "description": cost_line.desc,
                            "allocation_id": str(cost_line.id),
                        }
                    )
                    logger.debug(
                        f"Added CostLine allocation for line {line_id}: {cost_line.quantity} units to {cost_line.cost_set.job.name}"
                    )
                else:
                    logger.warning(
                        f"CostLine {cost_line.id} has no purchase_order_line_id in ext_refs: {cost_line.ext_refs}"
                    )

            # Process Stock items (stock allocations)
            for stock_item in stock_items:
                line_id = str(stock_item.source_purchase_order_line.id)
                if line_id not in allocations_by_line:
                    allocations_by_line[line_id] = []

                allocations_by_line[line_id].append(
                    {
                        "type": "stock",
                        "job_id": str(stock_item.job.id),
                        "job_name": (
                            "Stock"
                            if stock_item.job.name == "Worker Admin"
                            else stock_item.job.name
                        ),
                        "quantity": float(stock_item.quantity),
                        "retail_rate": (
                            float(stock_item.retail_rate * 100)
                            if stock_item.retail_rate
                            else 0
                        ),
                        "allocation_date": stock_item.date.isoformat(),
                        "description": stock_item.description,
                        "stock_location": stock_item.location or "Not specified",
                        "metal_type": stock_item.metal_type or "unspecified",
                        "alloy": stock_item.alloy or "",
                        "specifics": stock_item.specifics or "",
                        "allocation_id": str(stock_item.id),
                    }
                )
                logger.debug(
                    f"Added Stock allocation for line {line_id}: {stock_item.quantity} units to stock"
                )

            logger.info(
                f"Total allocations found: {sum(len(allocs) for allocs in allocations_by_line.values())} across {len(allocations_by_line)} lines"
            )

            # Serialize the response
            response_data = {"po_id": str(po_id), "allocations": allocations_by_line}

            serializer = self.serializer_class(response_data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error fetching allocations for PO {po_id}: {e}")
            return Response(
                {"error": f"Failed to fetch allocations: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class AllocationDeleteAPIView(APIView):
    """
    API endpoint to delete specific allocations from a purchase order.

    DELETE: Deletes a Stock item or CostLine allocation created from delivery receipt
    """

    serializer_class = AllocationDeleteResponseSerializer

    @extend_schema(
        request=AllocationDeleteSerializer,
        responses={
            status.HTTP_200_OK: AllocationDeleteResponseSerializer,
            status.HTTP_400_BAD_REQUEST: AllocationDeleteResponseSerializer,
        },
        operation_id="deleteAllocation",
        description="Delete a specific allocation (Stock item or CostLine) from a purchase order line.",
    )
    def post(self, request, po_id, line_id):
        """Delete a specific allocation from a purchase order line."""
        try:
            # Validate input data
            serializer = AllocationDeleteSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {
                        "success": False,
                        "message": "Invalid input data",
                        "details": serializer.errors,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            validated_data = serializer.validated_data
            allocation_type = validated_data["allocation_type"]
            allocation_id = str(validated_data["allocation_id"])

            # Delete the allocation using the service
            result = AllocationService.delete_allocation(
                po_id=str(po_id),
                line_id=line_id,
                allocation_type=allocation_type,
                allocation_id=allocation_id,
            )

            # Return success response
            response_serializer = self.serializer_class(result)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except AllocationDeletionError as e:
            logger.error(f"Allocation deletion error: {str(e)}")
            response_data = {"success": False, "message": str(e)}
            response_serializer = self.serializer_class(response_data)
            return Response(
                response_serializer.data, status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            traceback.print_exc()
            logger.error(f"Unexpected error deleting allocation: {str(e)}")
            response_data = {
                "success": False,
                "message": f"An unexpected error occurred: {str(e)}",
            }
            response_serializer = self.serializer_class(response_data)
            return Response(
                response_serializer.data, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class AllocationDetailsAPIView(APIView):
    """
    API endpoint to get details about a specific allocation before deletion.

    GET: Returns details about a Stock item or CostLine allocation
    """

    serializer_class = AllocationDetailsResponseSerializer

    @extend_schema(
        responses={
            status.HTTP_200_OK: AllocationDetailsResponseSerializer,
        },
        operation_id="getAllocationDetails",
        description="Get details about a specific allocation before deletion.",
    )
    def get(self, request, po_id, allocation_type, allocation_id):
        """Get details about a specific allocation."""
        try:
            # Get allocation details using the service
            details = AllocationService.get_allocation_details(
                po_id=po_id,
                allocation_type=allocation_type,
                allocation_id=allocation_id,
            )

            # Return details
            response_serializer = self.serializer_class(details)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Error getting allocation details: {str(e)}")
            return Response(
                {"error": f"Failed to get allocation details: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProductMappingListView(APIView):
    """
    REST API view for listing product parsing mappings.

    GET: Returns list of all product mappings with stats
    """

    serializer_class = ProductMappingListResponseSerializer

    @extend_schema(
        operation_id="listProductMappings",
        responses={
            status.HTTP_200_OK: ProductMappingListResponseSerializer,
        },
        tags=["Product Mapping"],
    )
    def get(self, request):
        """Get list of product mappings prioritizing unvalidated ones."""
        try:
            from apps.quoting.models import ProductParsingMapping

            # Get all mappings, prioritizing unvalidated ones first
            unvalidated = list(
                ProductParsingMapping.objects.filter(is_validated=False).order_by(
                    "-created_at"
                )
            )
            validated = list(
                ProductParsingMapping.objects.filter(is_validated=True).order_by(
                    "-validated_at"
                )
            )

            all_mappings = unvalidated + validated

            # Update Xero status for all mappings
            for mapping in all_mappings:
                mapping.update_xero_status()

            # Calculate stats
            total_count = len(all_mappings)
            validated_count = len(validated)
            unvalidated_count = len(unvalidated)

            # Serialize mappings
            mapping_serializer = ProductMappingSerializer(all_mappings, many=True)

            response_data = {
                "items": mapping_serializer.data,
                "total_count": total_count,
                "validated_count": validated_count,
                "unvalidated_count": unvalidated_count,
            }

            serializer = self.serializer_class(response_data)
            return Response(serializer.data)

        except Exception as e:
            logger.error(f"Error fetching product mappings: {str(e)}")
            return Response(
                {"error": "Failed to fetch product mappings", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProductMappingValidateView(APIView):
    """
    REST API view for validating a product parsing mapping.

    POST: Mark a mapping as validated and update related products
    """

    serializer_class = ProductMappingValidateResponseSerializer

    @extend_schema(
        operation_id="validateProductMapping",
        request=ProductMappingValidateSerializer,
        responses={
            status.HTTP_200_OK: ProductMappingValidateResponseSerializer,
            status.HTTP_400_BAD_REQUEST: ProductMappingValidateResponseSerializer,
            status.HTTP_404_NOT_FOUND: ProductMappingValidateResponseSerializer,
        },
        tags=["Product Mapping"],
    )
    def post(self, request, mapping_id):
        """Validate a product parsing mapping."""
        try:
            from django.utils import timezone

            from apps.quoting.models import ProductParsingMapping, SupplierProduct

            # Validate input data
            serializer = ProductMappingValidateSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {
                        "success": False,
                        "message": "Invalid input data",
                        "details": serializer.errors,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get mapping
            mapping = get_object_or_404(ProductParsingMapping, id=mapping_id)

            # Update validation status
            mapping.is_validated = True
            mapping.validated_by = request.user
            mapping.validated_at = timezone.now()

            # Update mapping fields from request
            validated_data = serializer.validated_data
            if "mapped_item_code" in validated_data:
                mapping.mapped_item_code = validated_data["mapped_item_code"]
            if "mapped_description" in validated_data:
                mapping.mapped_description = validated_data["mapped_description"]
            if "mapped_metal_type" in validated_data:
                mapping.mapped_metal_type = validated_data["mapped_metal_type"]
            if "mapped_alloy" in validated_data:
                mapping.mapped_alloy = validated_data["mapped_alloy"]
            if "mapped_specifics" in validated_data:
                mapping.mapped_specifics = validated_data["mapped_specifics"]
            if "mapped_dimensions" in validated_data:
                mapping.mapped_dimensions = validated_data["mapped_dimensions"]
            if "mapped_unit_cost" in validated_data:
                mapping.mapped_unit_cost = validated_data["mapped_unit_cost"]
            if "mapped_price_unit" in validated_data:
                mapping.mapped_price_unit = validated_data["mapped_price_unit"]
            if "validation_notes" in validated_data:
                mapping.validation_notes = validated_data["validation_notes"]

            # Update Xero status
            mapping.update_xero_status()
            mapping.save()

            # Backflow: Update all SupplierProducts that use this mapping
            update_count = SupplierProduct.objects.filter(
                mapping_hash=mapping.input_hash
            ).update(
                parsed_item_code=mapping.mapped_item_code,
                parsed_description=mapping.mapped_description,
                parsed_metal_type=mapping.mapped_metal_type,
                parsed_alloy=mapping.mapped_alloy,
                parsed_specifics=mapping.mapped_specifics,
                parsed_dimensions=mapping.mapped_dimensions,
                parsed_unit_cost=mapping.mapped_unit_cost,
                parsed_price_unit=mapping.mapped_price_unit,
            )

            logger.info(
                f"Validated mapping {mapping_id}, updated {update_count} related products"
            )

            response_data = {
                "success": True,
                "message": f"Mapping validated successfully. Updated {update_count} related products.",
                "updated_products_count": update_count,
            }

            response_serializer = self.serializer_class(response_data)
            return Response(response_serializer.data)

        except ProductParsingMapping.DoesNotExist:
            return Response(
                {"success": False, "message": "Mapping not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.error(f"Error validating mapping {mapping_id}: {str(e)}")
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PurchaseOrderPDFView(APIView):
    """
    REST API view for generating and downloading purchase order PDFs.

    GET: Returns the PDF file for the specified purchase order
    """

    serializer_class = PurchaseOrderPDFResponseSerializer

    @extend_schema(
        operation_id="getPurchaseOrderPDF",
        responses={
            status.HTTP_200_OK: OpenApiResponse(
                response=OpenApiTypes.BINARY,
                description="PDF file attachment",
            ),
            status.HTTP_404_NOT_FOUND: PurchasingErrorResponseSerializer,
            status.HTTP_500_INTERNAL_SERVER_ERROR: PurchasingErrorResponseSerializer,
        },
        description="Generate and download PDF for the specified purchase order.",
    )
    def get(self, request, po_id):
        """Generate and return PDF for a purchase order."""
        try:
            # Get the purchase order
            po = get_object_or_404(PurchaseOrder, id=po_id)

            # Generate PDF
            pdf_buffer = create_purchase_order_pdf(po)

            # Return PDF as file response
            response = FileResponse(
                pdf_buffer,
                content_type="application/pdf",
                as_attachment=True,
                filename=f"Purchase_Order_{po.po_number}.pdf",
            )

            return response

        except PurchaseOrder.DoesNotExist:
            return Response(
                {"error": "Purchase order not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.error(f"Error generating PDF for PO {po_id}: {str(e)}")
            return Response(
                {"error": "Failed to generate PDF", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PurchaseOrderEmailView(APIView):
    """
    REST API view for generating purchase order emails.

    POST: Generate email data for the specified purchase order
    """

    serializer_class = PurchaseOrderEmailResponseSerializer

    @extend_schema(
        operation_id="getPurchaseOrderEmail",
        request=PurchaseOrderEmailSerializer,
        responses={
            status.HTTP_200_OK: PurchaseOrderEmailResponseSerializer,
            status.HTTP_400_BAD_REQUEST: PurchaseOrderEmailResponseSerializer,
        },
        description="Generate email data for the specified purchase order.",
    )
    def post(self, request, po_id):
        """Generate email data for a purchase order."""
        try:
            # Validate input data
            serializer = PurchaseOrderEmailSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(
                    {
                        "success": False,
                        "message": "Invalid input data",
                        "details": serializer.errors,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get the purchase order
            po = get_object_or_404(PurchaseOrder, id=po_id)

            # Generate email data
            email_data = create_purchase_order_email(po)

            # Override recipient if provided in request
            validated_data = serializer.validated_data
            if validated_data.get("recipient_email"):
                email_data["email"] = validated_data["recipient_email"]

            # Add custom message if provided
            if validated_data.get("message"):
                custom_message = validated_data["message"]
                email_data["body"] = f"{custom_message}\n\n{email_data['body']}"

            # Return email data
            response_data = {
                "success": True,
                "email_subject": email_data["subject"],
                "email_body": email_data["body"],
                "mailto_url": email_data["mailto_url"],
                "message": "Email data generated successfully",
            }

            response_serializer = self.serializer_class(response_data)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        except PurchaseOrder.DoesNotExist:
            return Response(
                {"success": False, "message": "Purchase order not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        except ValueError as e:
            return Response(
                {"success": False, "message": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.error(f"Error generating email for PO {po_id}: {str(e)}")
            return Response(
                {
                    "success": False,
                    "message": "Failed to generate email",
                    "details": str(e),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PurchaseOrderEventListCreateView(APIView):
    """
    REST API view for listing and creating purchase order events/comments.

    GET: Returns list of events for a purchase order
    POST: Creates a new event/comment on a purchase order
    """

    def get_serializer_class(self):
        """Return appropriate serializer class based on request method."""
        if self.request.method == "POST":
            return PurchaseOrderEventCreateSerializer
        return PurchaseOrderEventsResponseSerializer

    @extend_schema(
        operation_id="listPurchaseOrderEvents",
        responses={
            status.HTTP_200_OK: PurchaseOrderEventsResponseSerializer,
            status.HTTP_404_NOT_FOUND: PurchasingErrorResponseSerializer,
        },
        description="List all events/comments for a purchase order.",
        tags=["Purchase Orders"],
    )
    def get(self, request, po_id):
        """Get list of events for a purchase order."""
        po = get_object_or_404(PurchaseOrder, id=po_id)
        events = po.events.all()  # Model default ordering: -timestamp

        serializer = PurchaseOrderEventsResponseSerializer({"events": events})
        return Response(serializer.data)

    @extend_schema(
        operation_id="createPurchaseOrderEvent",
        request=PurchaseOrderEventCreateSerializer,
        responses={
            status.HTTP_201_CREATED: PurchaseOrderEventCreateResponseSerializer,
            status.HTTP_400_BAD_REQUEST: PurchasingErrorResponseSerializer,
            status.HTTP_404_NOT_FOUND: PurchasingErrorResponseSerializer,
        },
        description="Create a new event/comment on a purchase order.",
        tags=["Purchase Orders"],
    )
    def post(self, request, po_id):
        """Create a new event on a purchase order."""
        # Validate input
        serializer = PurchaseOrderEventCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(
                {"error": "Invalid input data", "details": serializer.errors},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get purchase order
        po = get_object_or_404(PurchaseOrder, id=po_id)

        try:
            # Create event
            event = PurchaseOrderEvent.objects.create(
                purchase_order=po,
                staff=request.user,
                description=serializer.validated_data["description"],
            )

            response_data = {"success": True, "event": event}
            response_serializer = PurchaseOrderEventCreateResponseSerializer(
                response_data
            )
            return Response(response_serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            logger.error(f"Error creating event for PO {po_id}: {str(e)}")
            persist_app_error(e)
            return Response(
                {"error": "Failed to create event", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
