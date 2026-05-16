from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.purchasing.views.purchasing_rest_views import (
    AllJobsAPIView,
    AllocationDeleteAPIView,
    AllocationDetailsAPIView,
    DeliveryReceiptRestView,
    ProductMappingListView,
    ProductMappingValidateView,
    PurchaseOrderAllocationsAPIView,
    PurchaseOrderDetailRestView,
    PurchaseOrderEmailView,
    PurchaseOrderEventListCreateView,
    PurchaseOrderLastNumberAPIView,
    PurchaseOrderListCreateRestView,
    PurchaseOrderPDFView,
    PurchasingJobsAPIView,
    SupplierPriceStatusAPIView,
)
from apps.purchasing.views.stock_search_rest_view import StockSearchRestView
from apps.purchasing.views.stock_viewset import StockViewSet
from apps.purchasing.views.supplier_search_rest_view import SupplierSearchRestView

# Router for ViewSet-based endpoints
router = DefaultRouter()
router.register("stock", StockViewSet, basename="stock")

urlpatterns = [
    path(
        "supplier-price-status/",
        SupplierPriceStatusAPIView.as_view(),
        name="supplier_price_status_rest",
    ),
    path(
        "suppliers/search/",
        SupplierSearchRestView.as_view(),
        name="supplier_search_rest",
    ),
    path("all-jobs/", AllJobsAPIView.as_view(), name="purchasing_all_jobs_rest"),
    path("jobs/", PurchasingJobsAPIView.as_view(), name="purchasing_jobs_rest"),
    path(
        "purchase-orders/",
        PurchaseOrderListCreateRestView.as_view(),
        name="purchase_orders_rest",
    ),
    path(
        "purchase-orders/last-number/",
        PurchaseOrderLastNumberAPIView.as_view(),
        name="purchase_orders_last_number_rest",
    ),
    path(
        "delivery-receipts/",
        DeliveryReceiptRestView.as_view(),
        name="delivery_receipts_rest",
    ),
    path(
        "purchase-orders/<uuid:po_id>/",
        PurchaseOrderDetailRestView.as_view(),
        name="purchase_order_detail_rest",
    ),
    path(
        "purchase-orders/<uuid:po_id>/allocations/",
        PurchaseOrderAllocationsAPIView.as_view(),
        name="purchase_order_allocations_rest",
    ),
    path(
        "purchase-orders/<uuid:po_id>/lines/<uuid:line_id>/allocations/delete/",
        AllocationDeleteAPIView.as_view(),
        name="allocation_delete_rest",
    ),
    path(
        "purchase-orders/<uuid:po_id>/pdf/",
        PurchaseOrderPDFView.as_view(),
        name="purchase_order_pdf_rest",
    ),
    path(
        "purchase-orders/<uuid:po_id>/email/",
        PurchaseOrderEmailView.as_view(),
        name="purchase_order_email_rest",
    ),
    path(
        "purchase-orders/<uuid:po_id>/events/",
        PurchaseOrderEventListCreateView.as_view(),
        name="purchase_order_events_rest",
    ),
    path(
        "purchase-orders/<uuid:po_id>/allocations/<str:allocation_type>/<uuid:allocation_id>/details/",
        AllocationDetailsAPIView.as_view(),
        name="allocation_details_rest",
    ),
    path(
        "product-mappings/",
        ProductMappingListView.as_view(),
        name="product_mappings_rest",
    ),
    path(
        "product-mappings/<uuid:mapping_id>/validate/",
        ProductMappingValidateView.as_view(),
        name="product_mapping_validate_rest",
    ),
    # Stock search must come before the router include so it doesn't
    # match the StockViewSet detail pattern (`/stock/<pk>/`).
    path(
        "stock/search/",
        StockSearchRestView.as_view(),
        name="stock_search_rest",
    ),
    # ViewSet routes (stock CRUD)
    path("", include(router.urls)),
]
