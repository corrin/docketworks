import logging
import os
import tempfile

from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from drf_spectacular.utils import extend_schema
from rest_framework import status

from apps.quoting.serializers import (
    ExtractSupplierPriceListErrorSerializer,
    ExtractSupplierPriceListResponseSerializer,
    SupplierPriceListUploadSerializer,
)
from apps.quoting.services.ai_price_extraction import extract_price_data
from apps.quoting.services.pdf_data_validation import PDFDataValidationService
from apps.quoting.services.pdf_import_service import PDFImportService
from apps.workflow.services.error_persistence import persist_app_error

logger = logging.getLogger(__name__)


@extend_schema(
    operation_id="extractSupplierPriceList",
    summary="Upload and extract supplier price list PDF",
    description="""
Complete pipeline to upload supplier PDF, extract pricing with AI, validate, and import to database.

The endpoint:
1. Accepts a PDF file upload (max 10MB)
2. Extracts product pricing using AI (Gemini)
3. Validates the extracted data
4. Imports valid products to the database
5. Returns statistics and any warnings

The AI extraction identifies:
- Supplier name (or inferred from filename)
- Product names, descriptions, and item numbers
- Prices and units
- Available stock quantities
""",
    request={
        "multipart/form-data": SupplierPriceListUploadSerializer,
    },
    responses={
        status.HTTP_200_OK: ExtractSupplierPriceListResponseSerializer,
        status.HTTP_400_BAD_REQUEST: ExtractSupplierPriceListErrorSerializer,
        status.HTTP_413_REQUEST_ENTITY_TOO_LARGE: ExtractSupplierPriceListErrorSerializer,
        status.HTTP_500_INTERNAL_SERVER_ERROR: ExtractSupplierPriceListErrorSerializer,
    },
    tags=["Purchasing"],
)
@require_http_methods(["POST"])
def extract_supplier_price_list_data_view(request):
    """
    Complete supplier price list processing pipeline:
    1. Validate and save uploaded PDF
    2. Extract pricing data using AI
    3. Validate and sanitize extracted data
    4. Import products to database
    5. Return detailed processing results
    """
    temp_file_path = None

    try:
        # Step 1: Validate file upload
        if "price_list_file" not in request.FILES:
            return JsonResponse(
                {"success": False, "error": "No price list file uploaded."}, status=400
            )

        price_list_file = request.FILES["price_list_file"]

        # Validate file type
        if not price_list_file.content_type == "application/pdf":
            return JsonResponse(
                {"success": False, "error": "Please upload a valid PDF file."},
                status=400,
            )

        # Validate file size (10MB limit)
        max_size = 10 * 1024 * 1024  # 10MB
        if price_list_file.size > max_size:
            return JsonResponse(
                {"success": False, "error": "File size must be less than 10MB."},
                status=400,
            )

        logger.info(
            f"Processing supplier price list: {price_list_file.name}, size: {price_list_file.size} bytes, content_type: {price_list_file.content_type}"
        )

        # Step 2: Save file temporarily for processing
        logger.info("Saving file temporarily for processing...")
        with tempfile.NamedTemporaryFile(
            delete=False, suffix=os.path.splitext(price_list_file.name)[1]
        ) as temp_file:
            for chunk in price_list_file.chunks():
                temp_file.write(chunk)
            temp_file_path = temp_file.name

        logger.info(f"File saved to temporary path: {temp_file_path}")
        logger.info(f"Temporary file size: {os.path.getsize(temp_file_path)} bytes")

        # Step 3: Extract data using AI
        logger.info("Starting AI extraction...")
        try:
            extracted_data, extraction_error = extract_price_data(
                temp_file_path, price_list_file.content_type
            )
            logger.info(f"AI extraction completed. Error: {extraction_error}")
            if extracted_data:
                logger.info(f"Extracted data keys: {list(extracted_data.keys())}")
                if "items" in extracted_data:
                    logger.info(
                        f"Number of items extracted: {len(extracted_data['items'])}"
                    )
            else:
                logger.warning("No data extracted from AI provider")
        except Exception as ai_error:
            logger.exception(f"Exception during AI extraction: {ai_error}")
            return JsonResponse(
                {
                    "success": False,
                    "error": f"AI extraction exception: {str(ai_error)}",
                    "stage": "extraction",
                },
                status=500,
            )

        if extraction_error:
            return JsonResponse(
                {
                    "success": False,
                    "error": f"AI extraction failed: {extraction_error}",
                    "stage": "extraction",
                },
                status=400,
            )

        if not extracted_data or not extracted_data.get("items"):
            return JsonResponse(
                {
                    "success": False,
                    "error": "No product data could be extracted from the PDF",
                    "stage": "extraction",
                },
                status=400,
            )

        # Step 4: Validate extracted data
        logger.info("Validating extracted data...")
        validator = PDFDataValidationService()
        (
            is_valid,
            validation_errors,
            validation_warnings,
        ) = validator.validate_extracted_data(extracted_data)

        if not is_valid:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Extracted data validation failed",
                    "validation_errors": validation_errors,
                    "validation_warnings": validation_warnings,
                    "stage": "validation",
                },
                status=400,
            )

        # Step 5: Sanitize product data
        logger.info("Sanitizing product data...")
        products = validator.sanitize_product_data(extracted_data.get("items", []))

        if not products:
            return JsonResponse(
                {
                    "success": False,
                    "error": "No valid products found after data sanitization",
                    "validation_warnings": validation_warnings,
                    "stage": "validation",
                },
                status=400,
            )

        # Step 6: Database operations
        logger.info("Starting database import...")
        supplier_name = extracted_data.get("supplier", {}).get("name", "").strip()

        if not supplier_name:
            # Try to infer supplier name from filename
            supplier_name = os.path.splitext(price_list_file.name)[0]
            logger.info(f"Inferred supplier name from filename: {supplier_name}")

        logger.info(f"Supplier name: '{supplier_name}'")
        logger.info(f"Number of products to import: {len(products)}")
        logger.info(
            f"Sample product data: {products[0] if products else 'No products'}"
        )

        # Use atomic transaction for database operations
        try:
            with transaction.atomic():
                import_service = PDFImportService()

                # Create or get supplier
                logger.info("Creating/getting supplier...")
                supplier, supplier_created = import_service.create_or_get_supplier(
                    supplier_name
                )
                logger.info(f"Supplier created: {supplier_created}, ID: {supplier.id}")

                # Create price list record
                logger.info("Creating price list...")
                price_list = import_service.create_price_list(
                    supplier, price_list_file.name
                )
                logger.info(f"Price list created, ID: {price_list.id}")

                # Import products
                logger.info("Importing products...")
                duplicate_strategy = request.POST.get("duplicate_strategy", "skip")
                import_stats = import_service.import_products(
                    products, supplier, price_list, duplicate_strategy
                )
                logger.info(f"Import stats: {import_stats}")

        except Exception as db_error:
            logger.exception(f"Database import failed: {db_error}")
            return JsonResponse(
                {
                    "success": False,
                    "error": f"Database import failed: {str(db_error)}",
                    "stage": "database_import",
                },
                status=500,
            )

        # Step 7: Compile results
        results = {
            "success": True,
            "message": f"Successfully processed '{price_list_file.name}'",
            "supplier": {
                "name": supplier.name,
                "id": str(supplier.id),
                "created": supplier_created,
            },
            "price_list": {
                "id": str(price_list.id),
                "filename": price_list.file_name,
                "uploaded_at": price_list.uploaded_at.isoformat(),
            },
            "statistics": {
                "total_extracted": len(extracted_data.get("items", [])),
                "total_valid": len(products),
                "imported": import_stats.get("imported", 0),
                "updated": import_stats.get("updated", 0),
                "skipped": import_stats.get("skipped", 0),
                "failed": import_stats.get("failed", 0),
            },
            "validation": {
                "warnings": validation_warnings,
                "warning_count": len(validation_warnings),
            },
            "import_stats": import_service.get_import_stats(),
        }

        logger.info(f"Processing completed successfully: {import_stats}")
        return JsonResponse(results)

    except Exception as exc:
        app_error = persist_app_error(exc)
        logger.exception("Error in extract_supplier_price_list_data_view: %s", exc)
        return JsonResponse(
            {
                "success": False,
                "error": f"An unexpected error occurred: {str(exc)}",
                "stage": "processing",
                "error_id": str(app_error.id),
            },
            status=500,
        )
    finally:
        # Clean up temporary file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.unlink(temp_file_path)
            except Exception as e:
                logger.warning(
                    f"Failed to cleanup temporary file {temp_file_path}: {e}"
                )
