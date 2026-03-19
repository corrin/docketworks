import base64
import json
import logging
import os
import re
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from mistralai import Mistral

logger = logging.getLogger(__name__)


def encode_pdf(pdf_path):
    """Encode the PDF file to base64."""
    try:
        with open(pdf_path, "rb") as pdf_file:
            return base64.b64encode(pdf_file.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"Error encoding PDF: {str(e)}")
        return None


class MistralPriceExtractionProvider:
    """Mistral AI provider for price extraction using OCR"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    def get_provider_name(self) -> str:
        return "Mistral"

    def _extract_supplier_from_text(self, text: str) -> str:
        """Extract supplier name from the OCR text."""
        lines = text.split("\n")
        supplier_name = "Unknown Supplier"

        # Check for supplier name in footer pattern "**Company Name**"
        footer_pattern = r"\*\*([^*]+)\*\*"
        footer_matches = re.findall(footer_pattern, text)
        for match in footer_matches:
            if "customer" not in match.lower() and "morris" not in match.lower():
                # Found a potential supplier name in bold
                supplier_name = match.strip()

        # Check first 30 lines for company indicators
        for line in lines[:30]:
            line = line.strip()

            # Skip customer lines
            if "customer" in line.lower() or "morris" in line.lower():
                continue

            # Look for company indicators
            if any(
                indicator in line.upper()
                for indicator in ["LTD", "PTY", "INC", "CORP", "LLC", "COMPANY"]
            ):
                # Clean up the line
                cleaned = line.replace("|", "").replace("*", "").strip()
                if len(cleaned) > 5 and "customer" not in cleaned.lower():
                    return cleaned

        return supplier_name

    def _parse_price_from_string(self, price_str: str) -> Optional[float]:
        """Extract numeric price from a string like '$49.35' or '\\$ 49.35'."""
        if not price_str:
            return None

        # Remove LaTeX formatting, dollar signs, and spaces
        cleaned = price_str.replace("\\$", "").replace("$", "").strip()

        # Extract numeric value
        match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    def _parse_dimensions_from_description(
        self, description: str
    ) -> Dict[str, Optional[str]]:
        """Extract dimensions from product descriptions like '0.7 mm × 1200 × 2400'."""
        result = {
            "thickness": None,
            "width": None,
            "length": None,
            "diameter": None,
            "specifications": description,
        }

        # Clean up the description
        desc = (
            description.replace("\\mathrm{~mm}", "mm")
            .replace("\\times", "x")
            .replace("×", "x")
        )

        # Pattern for sheet products: thickness x width x length
        sheet_pattern = r"(\d+(?:\.\d+)?)\s*mm?\s*[xX]\s*(\d+)\s*[xX]\s*(\d+)"
        sheet_match = re.search(sheet_pattern, desc)
        if sheet_match:
            result["thickness"] = f"{sheet_match.group(1)}mm"
            result["width"] = sheet_match.group(2)
            result["length"] = sheet_match.group(3)
            return result

        # Pattern for tubes/angles: dimension1 x dimension2 (x dimension3)
        multi_dim_pattern = (
            r"(\d+(?:\.\d+)?)\s*[xX]\s*(\d+(?:\.\d+)?)\s*(?:[xX]\s*(\d+(?:\.\d+)?))?"
        )
        multi_match = re.search(multi_dim_pattern, desc)
        if multi_match:
            result["width"] = multi_match.group(1)
            result["length"] = multi_match.group(2)
            if multi_match.group(3):
                result["thickness"] = multi_match.group(3)
            return result

        return result

    def _extract_products_from_markdown_tables(
        self, markdown_text: str
    ) -> List[Dict[str, Any]]:
        """Extract product information from markdown tables in the OCR output."""
        products = []
        current_category = None

        lines = markdown_text.split("\n")
        i = 0

        while i < len(lines):
            line = lines[i].strip()

            # Detect category headers (e.g., "## 5005 Alloy Sheet", "# Channel")
            if line.startswith("#"):
                current_category = line.replace("#", "").strip()
                logger.info(f"Found category: {current_category}")

            # Detect table rows (lines with | separators)
            elif "|" in line and current_category:
                # Skip header rows
                if "Description" in line and "Price" in line:
                    i += 1
                    continue
                if line.strip() == "| --- | --- |" or line.strip() == "| :--: | :--: |":
                    i += 1
                    continue

                # Parse product row
                parts = [p.strip() for p in line.split("|") if p.strip()]
                if len(parts) >= 2:
                    description = parts[0]
                    price_str = parts[1] if len(parts) > 1 else None

                    # Skip if this looks like a header
                    if description.lower() in ["description", "eac price"]:
                        i += 1
                        continue

                    # Parse the price
                    unit_price = self._parse_price_from_string(price_str)

                    # Parse dimensions from description
                    dimensions = self._parse_dimensions_from_description(description)

                    # Extract item code if present (e.g., "UA1130" from the description)
                    item_code_match = re.search(r"UA\d+", description)
                    item_code = item_code_match.group(0) if item_code_match else ""

                    # Create variant ID from description
                    variant_id = description.replace(" ", "_").replace("/", "_")[:100]

                    product = {
                        "description": description,
                        "supplier_item_code": item_code,
                        "variant_id": variant_id,
                        "unit_price": unit_price,
                        "category": current_category,
                        "specifications": dimensions["specifications"],
                        "dimensions": {
                            "width": dimensions["width"],
                            "length": dimensions["length"],
                            "thickness": dimensions.get("thickness"),
                            "diameter": dimensions.get("diameter"),
                        },
                        "product_name": (
                            f"{current_category} - {description}"
                            if current_category
                            else description
                        ),
                    }

                    products.append(product)

            i += 1

        return products

    def _parse_ocr_to_price_data(
        self, client, ocr_response
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Parse OCR response into structured price data."""
        try:
            # Extract all text and markdown content
            all_text = ""
            all_markdown = ""
            pages_data = []

            if hasattr(ocr_response, "pages") and ocr_response.pages:
                for i, page in enumerate(ocr_response.pages, 1):
                    page_text = ""
                    page_markdown = ""

                    if hasattr(page, "markdown") and page.markdown:
                        page_markdown = page.markdown
                        page_text = page_markdown
                    elif hasattr(page, "text") and page.text:
                        page_text = page.text

                    if page_text:
                        all_text += page_text + "\n"
                        all_markdown += page_markdown + "\n" if page_markdown else ""
                        pages_data.append(
                            {
                                "page_number": i,
                                "text": page_text,
                                "markdown": page_markdown,
                            }
                        )

            if not all_text.strip():
                return None, "No text content extracted from PDF"

            # Extract supplier name
            supplier_name = self._extract_supplier_from_text(all_text)
            logger.info(f"Identified supplier: {supplier_name}")

            # Extract customer and date from the header table if available
            customer_name = ""
            date = ""

            # Look for customer info in the markdown
            customer_match = re.search(r"Customer:\s*\|\s*([^|]+)\|", all_markdown)
            if customer_match:
                customer_name = customer_match.group(1).strip()

            # Look for date info
            date_match = re.search(r"Date:\s*\|\s*([^|]+)\|", all_markdown)
            if date_match:
                date = date_match.group(1).strip().replace("$", "")

            # Extract products from markdown tables
            items = self._extract_products_from_markdown_tables(all_markdown)

            logger.info(f"Parsed {len(items)} products from OCR text")

            # Return structured data for Django ORM
            structured_data = {
                "supplier": {
                    "name": supplier_name,
                    "customer": customer_name,
                    "date": date,
                },
                "items": items,
                "raw_ocr_text": all_text,
                "pages": pages_data,
                "parsing_stats": {
                    "total_lines": len(all_text.split("\n")),
                    "items_found": len(items),
                    "pages_processed": len(pages_data),
                },
            }

            logger.info(
                f"Final parsing results: supplier={supplier_name}, customer={customer_name}, {len(items)} items, {len(pages_data)} pages"
            )
            return structured_data, None

        except Exception as e:
            logger.error(f"Error parsing OCR to price data: {e}")
            return None, str(e)

    def extract_price_data(
        self, file_path: str, content_type: Optional[str] = None
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Extract OCR data using Mistral."""
        try:
            # Initialize the client
            if not self.api_key:
                raise ValueError("MISTRAL_API_KEY not provided")

            client = Mistral(api_key=self.api_key)

            # File handling
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"PDF file not found: {file_path}")

            logger.info("Processing PDF with Mistral OCR...")
            # Encode the PDF to base64
            base64_pdf = encode_pdf(file_path)
            if not base64_pdf:
                raise ValueError("Failed to encode PDF file")
            # Process the document with OCR
            ocr_response = client.ocr.process(
                model="mistral-ocr-latest",
                document={
                    "type": "document_url",
                    "document_url": f"data:application/pdf;base64,{base64_pdf}",
                },
                include_image_base64=True,
            )

            # Convert OCR response to a serializable dictionary
            def ocr_response_to_dict(ocr_obj):
                if hasattr(ocr_obj, "__dict__"):
                    return {
                        k: ocr_response_to_dict(v) for k, v in ocr_obj.__dict__.items()
                    }
                elif isinstance(ocr_obj, list):
                    return [ocr_response_to_dict(item) for item in ocr_obj]
                else:
                    return ocr_obj

            # Save the results to a JSON file with input filename
            base_filename = os.path.splitext(os.path.basename(file_path))[0]
            json_output_file = os.path.join(
                tempfile.gettempdir(), f"{base_filename}_ocr_results.json"
            )
            with open(json_output_file, "w") as f:
                json.dump(ocr_response_to_dict(ocr_response), f, indent=2)
            logger.info("OCR processing complete!")
            logger.info(f"JSON results saved to: {os.path.abspath(json_output_file)}")
            # Log a preview of the results
            logger.debug("Preview of the OCR results (first page):")
            if hasattr(ocr_response, "pages") and ocr_response.pages:
                first_page = ocr_response.pages[0]
                logger.debug(f"Page 1 of {len(ocr_response.pages)}:")
                # Try to get markdown content first, fall back to text
                if hasattr(first_page, "markdown") and first_page.markdown:
                    preview = first_page.markdown[:500]
                    logger.debug(
                        preview + ("..." if len(first_page.markdown) > 500 else "")
                    )
                elif hasattr(first_page, "text") and first_page.text:
                    preview = first_page.text[:500]
                    logger.debug(
                        preview + ("..." if len(first_page.text) > 500 else "")
                    )
                else:
                    logger.debug("No text content available for preview")
            else:
                logger.warning("No pages found in the OCR response.")
            logger.info("Full results have been saved to:")
            logger.info(f"- {os.path.abspath(json_output_file)}")
            logger.info("JSON output saved for testing/debugging")

            # Now parse the OCR text into structured price data
            return self._parse_ocr_to_price_data(client, ocr_response)

        except Exception as e:
            logger.error(f"An error occurred: {str(e)}")
            if "retry_after" in str(e).lower():
                logger.warning(
                    "The server is processing your request. Please try again in a few moments."
                )
            return None, str(e)
