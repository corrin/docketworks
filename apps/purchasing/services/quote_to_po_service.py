import base64
import json
import logging
import os
from typing import Optional, Tuple, cast, overload

import anthropic
import pdfplumber
from anthropic.types import (
    DocumentBlockParam,
    ImageBlockParam,
    MessageParam,
    TextBlockParam,
)
from django.conf import settings
from google import genai
from pydantic import BaseModel, ConfigDict, Field
from rapidfuzz import fuzz, process

from apps.client.models import Client
from apps.job.enums import MetalType
from apps.purchasing.models import (
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderSupplierQuote,
)
from apps.workflow.enums import AIProviderTypes
from apps.workflow.models import AIProvider

logger = logging.getLogger(__name__)

# Global flag to control PDF parser usage
USE_PDF_PARSER = False


QuoteScalar = str | int | float


class SupplierQuoteBaseModel(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, populate_by_name=True)


class SupplierQuoteSupplierModel(SupplierQuoteBaseModel):
    name: str | None = None
    address: str | None = None
    original_name: str | None = None


class MatchedSupplierModel(SupplierQuoteBaseModel):
    id: str
    name: str
    xero_contact_id: str | None


class SupplierQuoteItemModel(SupplierQuoteBaseModel):
    description: str | None = None
    quantity: QuoteScalar | None = None
    dimensions: str | None = None
    unit_price: QuoteScalar | None = None
    line_total: QuoteScalar | None = None
    supplier_item_code: str | None = None
    metal_type: str | None = None
    alloy: str | None = None
    specifics: str | None = None


class SupplierQuotePayloadModel(SupplierQuoteBaseModel):
    supplier: SupplierQuoteSupplierModel
    quote_reference: str | None = None
    line_items: list[SupplierQuoteItemModel] = Field(alias="items")
    matched_supplier: MatchedSupplierModel | None = None


def normalize(s: str) -> str:
    """Normalize a string for comparison."""
    if not s:
        return ""
    return " ".join(
        s.lower().split()
    )  # lower, remove extra whitespace, preserve everything else


def fuzzy_find_supplier(supplier_name: str) -> tuple[Client | None, str]:
    """
    Find a supplier in the database using fuzzy matching.

    Args:
        supplier_name (str): The supplier name to match

    Returns:
        tuple: (matched_supplier, original_name) - The matched supplier object and the original name
    """
    if not supplier_name.strip():
        raise ValueError("Supplier name must be a non-empty string")

    # Get all suppliers
    suppliers = Client.objects.all()

    # Extract supplier names and create a mapping from name to supplier object
    supplier_names = [s.name for s in suppliers]
    supplier_map = {s.name: s for s in suppliers}

    # Build a map from normalized -> original so we can return the true supplier name
    norm_map = {normalize(name): name for name in supplier_names}
    norm_names = list(norm_map.keys())

    # Normalize the input supplier name
    norm_supplier = normalize(supplier_name)

    # Find the best match
    if not norm_names:
        # No suppliers in database
        logger.warning(f"No suppliers in database to match against: {supplier_name}")
        return None, supplier_name

    match, score, _ = process.extractOne(
        norm_supplier, norm_names, scorer=fuzz.token_set_ratio
    )

    # Use a threshold to ensure the match is good enough
    if score < 85:
        # Score too low
        logger.warning(f"No supplier match found for: {supplier_name}")
        return None, supplier_name

    original_name = norm_map[match]
    matched_supplier = supplier_map[original_name]
    logger.info(
        f"Found fuzzy supplier match: '{supplier_name}' -> '{original_name}' (score: {score})"
    )
    return matched_supplier, supplier_name


def save_quote_file(purchase_order, file_obj):
    """Save a supplier quote file and create a PurchaseOrderSupplierQuote record."""
    # Create quotes folder if it doesn't exist
    quotes_folder = os.path.join(settings.DROPBOX_WORKFLOW_FOLDER, "PO_Quotes")
    os.makedirs(quotes_folder, exist_ok=True)

    # Create a unique filename
    filename = f"{purchase_order.po_number}_{file_obj.name}"
    file_path = os.path.join(quotes_folder, filename)

    # Save the file
    with open(file_path, "wb") as destination:
        for chunk in file_obj.chunks():
            destination.write(chunk)

    # Create the record
    relative_path = os.path.relpath(file_path, settings.DROPBOX_WORKFLOW_FOLDER)
    quote = PurchaseOrderSupplierQuote.objects.create(
        purchase_order=purchase_order,
        filename=filename,
        file_path=relative_path,
        mime_type=file_obj.content_type,
    )

    return quote


def extract_data_from_supplier_quote(
    quote_path: str,
    content_type: str | None = None,
    use_pdf_parser: bool = USE_PDF_PARSER,
) -> tuple[SupplierQuotePayloadModel | None, str | None]:
    """Extract data from a supplier quote file using Claude."""
    try:
        # Get the active AI provider and its API key
        default_ai_provider = AIProvider.objects.filter(default=True).first()

        if not default_ai_provider:
            return (
                None,
                "No active AI provider configured. Please set one in company settings.",
            )

        if default_ai_provider.provider_type != AIProviderTypes.ANTHROPIC:
            return (
                None,
                f"Configured AI provider is {default_ai_provider.provider_type}, but this function requires Anthropic (Claude).",
            )

        api_key = default_ai_provider.api_key

        if not api_key:
            return (
                None,
                "Anthropic API key not configured for the active AI provider. Please add it in company settings.",
            )

        if not default_ai_provider.model_name:
            return (
                None,
                "Anthropic model name not configured for the active AI provider. Please add it in company settings.",
            )

        # Read and encode the file
        with open(quote_path, "rb") as file:
            file_content = file.read()
        file_b64 = base64.b64encode(file_content).decode("utf-8")

        # Determine if this is a PDF
        is_pdf = content_type == "application/pdf" or quote_path.lower().endswith(
            ".pdf"
        )

        # Extract text from PDF if requested
        extracted_text = None
        logger.info(f"PDF extraction: is_pdf={is_pdf}, use_pdf_parser={use_pdf_parser}")

        if is_pdf and use_pdf_parser:
            try:
                text = []
                with pdfplumber.open(quote_path) as pdf:
                    for page in pdf.pages:
                        text.append(page.extract_text())
                extracted_text = "\n\n".join(text)
                logger.info(f"Extracted {len(extracted_text)} characters from PDF")
                # Log a shorter version of the extracted text for debugging
                preview_length = min(10000, len(extracted_text))
                logger.info(
                    f"PDF TEXT PREVIEW (first {preview_length} chars): {extracted_text[:preview_length]}"
                )
                # Log the full text if needed for detailed debugging
                logger.debug(f"FULL PDF EXTRACTED TEXT: {extracted_text}")
            except Exception as e:
                logger.error(f"Failed to extract text from PDF: {e}")
                # Continue with the original PDF if text extraction fails

        # Determine media type and content type
        if is_pdf and not use_pdf_parser:
            # Send PDF directly
            api_content_type = "document"
            media_type = "application/pdf"
        elif content_type and content_type.startswith("image/"):
            # Send image directly
            api_content_type = "image"
            media_type = content_type
        else:
            # Send as text (either extracted from PDF or other text format)
            api_content_type = "text"
            media_type = "text/plain"

        logger.info(
            f"File type detection: path={quote_path}, content_type={content_type}, is_pdf={is_pdf}, use_pdf_parser={use_pdf_parser}"
        )

        # Get valid metal types for the prompt
        valid_metal_types = [choice[0] for choice in MetalType.choices]
        metal_types_str = ", ".join(valid_metal_types)

        # Create the prompt
        prompt = f"""
        Based on this quote document, please create a complete purchase order in JSON format with the following structure:

        {{
        "supplier": {{
            "name": "Supplier Name",
            "address": "Supplier Address (if available)"
        }},
        "quote_reference": "Quote reference number (if available)",
        "items": [
            {{
            "description": "EXACT raw text description from the quote",
            "quantity": "Quantity as a numeric value only (e.g., 2, 3.5)",
            "dimensions": "Length, width, height, etc. if available",
            "unit_price": "Unit price as shown in the quote",
            "line_total": "Total cost for this line item as a numeric value only (e.g., 542.40)",
            "supplier_item_code": "Supplier's item code or SKU if available",
            "metal_type": "Type of metal (one of: {metal_types_str})",
            "alloy": "Alloy specification (if available)",
            "specifics": "Any specific details about grade, etc."
            }}
        ]
        }}

        IMPORTANT INSTRUCTIONS:
        1. Extract the "description" EXACTLY as it appears in the quote
        2. For "quantity" and "line_total", extract ONLY the numeric values (remove currency symbols, commas, etc.)
        3. For "unit_price", keep the original format including any price units (e.g., "per meter", "each")
        4. For "metal_type", ONLY use one of the following: {metal_types_str}
        5. If a price format contains units like "$/m" or "per meter", capture that in unit_price but extract the numeric line_total
        6. Do not guess values—leave them null or omit the field if unknown
        7. Return ONLY a single valid JSON object in the format above

        DO NOT return a JSON array of line items on their own—embed them in the full structure.

        Example output:
        {{
        "supplier": {{
            "name": "Abel Metal Products (2020) Ltd",
            "address": "12 Industrial Way, Penrose, Auckland"
        }},
        "quote_reference": "Q-12345",
        "items": [
            {{
            "description": "2m length of 50mm x 50mm x 3mm SHS Grade 350",
            "quantity": 6,
            "dimenisons": "2m",
            "unit_price": "90.40ea",
            "line_total": 542.40,
            "supplier_item_code": "SHS-50-3-350",
            "metal_type": "mild_steel",
            "alloy": "350",
            "specifics": "50mm x 50mm x 3mm SHS"
            }}
        ]
        }}
        """

        # Call Claude API via the SDK. Cache the prompt block (large, identical
        # across every quote) so the second+ extraction within ~5 min pays ~10%
        # of the input cost.
        client = anthropic.Anthropic(api_key=api_key)
        content_blocks: list[TextBlockParam | ImageBlockParam | DocumentBlockParam] = [
            {
                "type": "text",
                "text": prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        if extracted_text is not None and extracted_text.strip():
            content_blocks.append({"type": "text", "text": extracted_text})
        elif is_pdf:
            content_blocks.append(
                cast(
                    DocumentBlockParam,
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": file_b64,
                        },
                    },
                )
            )
        elif api_content_type == "image":
            content_blocks.append(
                cast(
                    ImageBlockParam,
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": file_b64,
                        },
                    },
                )
            )
        else:
            content_blocks.append(
                {"type": "text", "text": file_content.decode("utf-8", errors="replace")}
            )
        messages: list[MessageParam] = [{"role": "user", "content": content_blocks}]
        response = client.messages.create(
            model=default_ai_provider.model_name,
            max_tokens=4000,
            messages=messages,
        )

        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        total_tokens = input_tokens + output_tokens

        logger.info(
            f"Claude API token usage for quote extraction: "
            f"Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}"
        )

        json_text = ""
        for block in response.content:
            if block.type == "text":
                json_text += block.text

        # Clean up JSON text
        json_text = json_text.strip()
        if json_text.startswith("```json"):
            json_text = json_text[7:]
        if json_text.endswith("```"):
            json_text = json_text[:-3]

        json_text = json_text.strip()

        # Parse and validate untrusted model output at the AI boundary.
        quote_data = SupplierQuotePayloadModel.model_validate(json.loads(json_text))

        supplier_name_from_quote = extract_supplier_name(quote_data)
        if supplier_name_from_quote:
            matched_supplier, original_name = fuzzy_find_supplier(
                supplier_name_from_quote
            )
            supplier = quote_data.supplier.model_copy(
                update={"original_name": original_name}
            )
            matched_supplier_data = None
            if matched_supplier:
                matched_supplier_data = MatchedSupplierModel(
                    id=str(matched_supplier.id),
                    name=matched_supplier.name,
                    xero_contact_id=matched_supplier.xero_contact_id,
                )
            quote_data = quote_data.model_copy(
                update={
                    "supplier": supplier,
                    "matched_supplier": matched_supplier_data,
                }
            )
        else:
            logging.warning("Supplier name not found in quote JSON")

        # Return the extracted data
        return quote_data, None

    except Exception as e:
        logger.exception(f"Error extracting data from supplier quote: {e}")
        return None, str(e)


def read_file_content(file_path: str) -> Optional[bytes]:
    """Read file content in binary mode."""
    try:
        with open(file_path, "rb") as file:
            return file.read()
    except Exception as e:
        logger.error(f"Failed to read file {file_path}: {e}")
        return None


def create_concise_prompt(metal_types: list[str]) -> str:
    """Generates a more concise prompt for Supplier Quote data extraction"""

    metal_types_str = ", ".join(metal_types)

    return f"""
        Extract ONLY the essential purchase order data from this document in JSON format:

        {{
        "supplier": {{
            "name": "Supplier Name"
        }},
        "quote_reference": "Quote reference number (if available)",
        "items": [
            {{
            "description": "EXACT raw text description from the quote",
            "quantity": "Numeric value only",
            "unit_price": "Unit price if available",
            "line_total": "Total cost as numeric value",
            "supplier_item_code": "Supplier's item code if available",
            "metal_type": "One of: {metal_types_str}",
            "dimensions": "Dimensions if available"
            }}
        ]
        }}

        IMPORTANT:
        1. Extract descriptions EXACTLY as they appear
        2. Extract ONLY numeric values for quantities and totals
        3. Only use valid metal types from the list provided
        4. Do not guess or add information not in the document
        5. Return ONLY a valid JSON object
        """


def clean_json_response(text: str) -> str:
    """Clean up JSON response by removing markdown code blocks."""
    text = text.strip()

    if "```json" in text:
        text = text.split("```json")[1]
        if "```" in text:
            text = text.split("```")[0]
    elif "```" in text:
        text = text.replace("```", "")

    return text.strip()


def extract_supplier_name(quote_data: SupplierQuotePayloadModel) -> str | None:
    """Return the extracted supplier name when one is available for matching."""
    supplier_name = quote_data.supplier.name
    if supplier_name is None or not supplier_name.strip():
        return None
    return supplier_name


def process_supplier_data(
    quote_data: SupplierQuotePayloadModel,
) -> SupplierQuotePayloadModel:
    """Process supplier matching from quote data."""
    supplier_name = extract_supplier_name(quote_data)
    if supplier_name:
        matched_supplier, original_name = fuzzy_find_supplier(supplier_name)

        supplier = quote_data.supplier.model_copy(
            update={"original_name": original_name}
        )
        matched_supplier_data = None
        if matched_supplier:
            matched_supplier_data = MatchedSupplierModel(
                id=str(matched_supplier.id),
                name=matched_supplier.name,
                xero_contact_id=matched_supplier.xero_contact_id,
            )
        quote_data = quote_data.model_copy(
            update={
                "supplier": supplier,
                "matched_supplier": matched_supplier_data,
            }
        )
    else:
        logging.warning("Supplier name not found in quote JSON")

    return quote_data


def create_po_line_from_quote_item(
    purchase_order: PurchaseOrder, line_data: SupplierQuoteItemModel
) -> Optional[PurchaseOrderLine]:
    """Create a PO line from quote item data."""
    description = line_data.description or ""
    if not description:
        logger.warning("Skipping line item with no description")
        return None

    quantity = safe_float(line_data.quantity, 1)
    line_total = safe_float(line_data.line_total, 0)
    unit_price = safe_float(line_data.unit_price)

    unit_cost = calculate_unit_cost(quantity, line_total, unit_price, description)

    return PurchaseOrderLine.objects.create(
        purchase_order=purchase_order,
        description=description,
        quantity=quantity,
        unit_cost=unit_cost,
        price_tbc=unit_cost is None,
        supplier_item_code=line_data.supplier_item_code or "",
        metal_type=line_data.metal_type or "unspecified",
        alloy=line_data.alloy or "",
        specifics=line_data.specifics or "",
        dimensions=line_data.dimensions or "",
        raw_line_data=line_data.model_dump(mode="json", exclude_none=True),
    )


@overload
def safe_float(value: QuoteScalar | None, default: float) -> float: ...


@overload
def safe_float(value: QuoteScalar | None, default: None = None) -> float | None: ...


def safe_float(value: QuoteScalar | None, default: float | None = None) -> float | None:
    """Safely convert value to float with a default."""
    if value is None:
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def calculate_unit_cost(
    quantity: float,
    line_total: float,
    extracted_unit_price: Optional[float],
    description: str,
) -> Optional[float]:
    """Calculate unit cost from quantity and line total."""
    if not (line_total > 0 and quantity > 0):
        logger.warning(
            f"Could not calculate unit cost for: '{description}, "
            f"Line total: {line_total}, Quantity: {quantity}"
        )
        return None

    unit_cost = line_total / quantity

    if (
        extracted_unit_price is not None
        and abs(unit_cost - extracted_unit_price) > 0.01
    ):
        logger.warning(
            f"Unit cost discrepancy for: '{description}', "
            f"Calculated: {unit_cost:.2f} vs. Extracted: {extracted_unit_price:.2f}. "
            f" Using calculated value."
        )
    return unit_cost


def log_token_usage(usage, api_name):
    """Log token usage from AI API response."""
    input_tokens = getattr(usage, "input_tokens", 0)
    output_tokens = getattr(usage, "output_tokens", 0)
    total_tokens = input_tokens + output_tokens

    logger.info(
        f"{api_name} API token usage for quote extraction: "
        f"Input: {input_tokens}, Output: {output_tokens}, Total: {total_tokens}"
    )


def extract_data_from_supplier_quote_gemini(
    quote_path: str,
    content_type: Optional[str] = None,
    ai_provider: Optional[AIProvider] = None,
) -> Tuple[Optional[SupplierQuotePayloadModel], Optional[str]]:
    """
    Extract data from a supplier quote file using Gemini,

    Args:
        quote_path: Path to the quote file
        content_type: MIME type of the file (optional)
        ai_provider: Optional AI provider to use, will get active one if not provided

    Returns:
        Tuple containing (quote_data, error_message)
    """
    try:
        if not ai_provider:
            ai_provider = AIProvider.objects.filter(default=True).first()

        if not ai_provider:
            return (
                None,
                "No active AI provider configured. Please set one in company settings.",
            )

        if ai_provider.provider_type != AIProviderTypes.GOOGLE:
            return (
                None,
                f"Configured AI provider is {ai_provider.provider_type}, but this function requires Google (Gemini).",
            )

        gemini_api_key = ai_provider.api_key

        if not gemini_api_key:
            return (
                None,
                "Gemini API key not configured for the active AI provider. Please add it in company settings.",
            )

        if not ai_provider.model_name:
            return (
                None,
                "Gemini model name not configured for the active AI provider. Please add it in company settings.",
            )

        client = genai.Client(api_key=gemini_api_key)

        with open(quote_path, "rb") as file:
            file_content = file.read()

        is_pdf = content_type == "application/pdf" or quote_path.lower().endswith(
            ".pdf"
        )
        is_image = content_type and content_type.startswith("image/")

        # I simplified the prompt to avoid overcooking the file.
        valid_metal_types = [choice[0] for choice in MetalType.choices]
        prompt = create_concise_prompt(valid_metal_types)

        contents = []
        contents.append({"text": prompt})

        if is_pdf:
            mime_type = "application/pdf"
            file_b64 = base64.b64encode(file_content).decode("utf-8")
            contents.append({"inline_data": {"mime_type": mime_type, "data": file_b64}})

        if is_image:
            mime_type = content_type or "image/jpeg"
            file_b64 = base64.b64encode(file_content).decode("utf-8")
            contents.append({"inline_data": {"mime_type": mime_type, "data": file_b64}})

        if not is_image or not is_pdf:
            try:
                text_content = file_content.decode("utf-8", errors="ignore")
                contents.append({"text": text_content})
            except Exception as e:
                logger.error(f"Failed to decode as text: {e}")
                return None, f"Failed to process file: {str(e)}"

        response = client.models.generate_content(
            model=ai_provider.model_name,
            contents=contents,
            config={
                "max_output_tokens": 4000,
                "temperature": 0.1,
                "response_mime_type": "application/json",
            },
        )

        if hasattr(response, "usage"):
            log_token_usage(response.usage, "Gemini")

        result_text = clean_json_response(response.text)
        quote_data = process_supplier_data(
            SupplierQuotePayloadModel.model_validate(json.loads(result_text))
        )

        return quote_data, None

    except json.JSONDecodeError as e:
        logger.exception(f"Error decoding JSON from Gemini response: {e}")
        return None, f"Invalid JSON response from Gemini: {str(e)}"
    except Exception as e:
        logger.exception(f"Error extracting data from supplier quote with Gemini: {e}")
        return None, str(e)


def create_po_from_quote(
    purchase_order: PurchaseOrder,
    quote: PurchaseOrderSupplierQuote,
    ai_provider: AIProvider,
) -> Tuple[Optional[PurchaseOrder], Optional[str]]:
    """
    Create purchase order lines from a supplier quote.

    Args:
        purchase_order: The purchase order to add lines to
        quote: The supplier quote to extract data from
        ai_provider: Optional, defines the AI provider to be used in the function
    """
    # Guard clause for AI provider
    if not ai_provider:
        error_msg = "No AI provider provided for quote processing"
        logger.error(error_msg)
        return None, error_msg

    quote_path = os.path.join(settings.DROPBOX_WORKFLOW_FOLDER, quote.file_path)

    match ai_provider.provider_type:
        case AIProviderTypes.GOOGLE:
            logger.info(f"Using Gemini for quote extraction: {quote.filename}")
            quote_data, error = extract_data_from_supplier_quote_gemini(
                quote_path, quote.mime_type, ai_provider=ai_provider
            )
        case AIProviderTypes.ANTHROPIC:
            logger.info(f"Using Claude for quote extraction: {quote.filename}")
            quote_data, error = extract_data_from_supplier_quote(
                quote_path, quote.mime_type
            )
        case _:
            err_msg = f"Invalid AI provider received: {ai_provider}."
            logger.error(err_msg)
            error = err_msg

    if error:
        return None, error
    if quote_data is None:
        return None, "No quote data was extracted"

    quote.extracted_data = quote_data.model_dump(
        mode="json",
        by_alias=True,
        exclude_none=True,
    )
    quote.save()

    items = quote_data.line_items
    if not items:
        return purchase_order, "No items found in quote"

    for line_data in items:
        po_line = create_po_line_from_quote_item(purchase_order, line_data)
        if po_line:
            logger.info(f"Created PO line: {po_line.description[:30]}...")

    return purchase_order, None
