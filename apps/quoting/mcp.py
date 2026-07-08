from functools import reduce

from django.db.models import Q
from mcp_server import MCPToolset, ModelQueryToolset

from apps.company.models import Company
from apps.job.models import Job

from .models import ScrapeJob, SupplierPriceList, SupplierProduct
from .utils import calculate_sheet_tenths


class SupplierProductQueryTool(ModelQueryToolset):
    """MCP tool for querying supplier products"""

    model = SupplierProduct
    exclude_fields = ["supplier", "price_list"]

    def get_queryset(self):
        return super().get_queryset().select_related("supplier", "price_list")


class QuotingTool(MCPToolset):
    """Custom MCP tools for quoting operations"""

    def search_products(self, query: str, supplier_name: str = None) -> str:
        """Search supplier products by description or specifications"""
        products = SupplierProduct.objects.all()

        if supplier_name:
            products = products.filter(supplier__name__icontains=supplier_name)

        products = products.filter(
            Q(product_name__icontains=query)
            | Q(description__icontains=query)
            | Q(specifications__icontains=query)
            | Q(parsed_description__icontains=query)
        )[
            :20
        ]  # Limit results

        if not products:
            return "No products found matching your search criteria."

        results = []
        for product in products:
            result = (
                f"• {product.supplier.name} - {product.product_name}\n"
                f"  Item: {product.item_no} | Price: ${product.variant_price or 'N/A'} {product.price_unit or ''}\n"
                f"  Description: {product.description or 'No description'}\n"
            )
            if product.url:
                result += f"  URL: {product.url}\n"
            results.append(result)

        return "\n".join(results)

    def get_pricing_for_material(
        self, material_type: str, dimensions: str = None
    ) -> str:
        """Get pricing information for specific materials"""
        products = SupplierProduct.objects.filter(
            parsed_metal_type__icontains=material_type
        )

        if dimensions:
            products = products.filter(
                Q(parsed_dimensions__icontains=dimensions)
                | Q(variant_width__icontains=dimensions)
                | Q(variant_length__icontains=dimensions)
            )

        products = products.select_related("supplier")[:15]

        if not products:
            return f"No pricing found for {material_type} with those specifications."

        results = [f"Pricing for {material_type}:"]
        for product in products:
            price_info = (
                f"${product.variant_price}" if product.variant_price else "Price TBA"
            )
            result = (
                f"• {product.supplier.name}: {product.product_name}\n"
                f"  {price_info} {product.price_unit or ''} | Dimensions: {product.parsed_dimensions or 'N/A'}\n"
            )
            if product.url:
                result += f"  URL: {product.url}\n"
            results.append(result)

        return "\n".join(results)

    def create_quote_estimate(
        self, job_id: str, materials: str, labor_hours: float = None
    ) -> str:
        """Create a quote estimate for a job"""
        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist:
            return f"Job with ID {job_id} not found."

        # Create a basic quote structure
        quote_info = [
            f"Quote Estimate for Job: {job.name}",
            f"Company: {job.company.name}",
            f"Materials requested: {materials}",
            "",
        ]

        # Search for relevant materials in supplier products
        material_keywords = materials.lower().split()
        relevant_products = SupplierProduct.objects.filter(
            reduce(
                lambda q, keyword: q
                | Q(product_name__icontains=keyword)
                | Q(parsed_description__icontains=keyword),
                material_keywords,
                Q(),
            )
        ).select_related("supplier")[:10]

        if relevant_products:
            quote_info.append("Suggested materials from suppliers:")
            total_estimate = 0
            for product in relevant_products:
                if product.variant_price:
                    quote_info.append(
                        f"• {product.supplier.name}: {product.product_name} - "
                        f"${product.variant_price} {product.price_unit or ''}"
                    )
                    try:
                        total_estimate += float(product.variant_price)
                    except (ValueError, TypeError):
                        pass

            if total_estimate > 0:
                quote_info.append(f"\nEstimated materials cost: ${total_estimate:.2f}")

        if labor_hours:
            labor_cost = labor_hours * 85  # Default rate
            quote_info.append(
                f"Labor estimate: {labor_hours} hours × $85/hr = ${labor_cost:.2f}"
            )

        return "\n".join(quote_info)

    def get_supplier_status(self, supplier_name: str = None) -> str:
        """Get status of supplier scraping and price lists"""
        if supplier_name:
            suppliers = Company.objects.filter(
                name__icontains=supplier_name, is_supplier=True
            )
        else:
            suppliers = Company.objects.filter(is_supplier=True)

        results = ["Supplier Status Report:"]

        for supplier in suppliers[:10]:  # Limit to 10 suppliers
            product_count = SupplierProduct.objects.filter(supplier=supplier).count()
            recent_scrape = ScrapeJob.objects.filter(supplier=supplier).first()
            price_lists_count = SupplierPriceList.objects.filter(
                supplier=supplier
            ).count()

            status_info = [
                f"\n• {supplier.name}:",
                f"  Products: {product_count}",
                f"  Price Lists: {price_lists_count}",
            ]

            if recent_scrape:
                status_info.append(
                    f"  Last Scrape: {recent_scrape.started_at.strftime('%Y-%m-%d')} "
                    f"({recent_scrape.status})"
                )
                if recent_scrape.products_scraped:
                    status_info.append(
                        f"  Products Scraped: {recent_scrape.products_scraped}"
                    )
            else:
                status_info.append("  Last Scrape: Never")

            results.extend(status_info)

        return "\n".join(results)

    def compare_suppliers(self, material_query: str) -> str:
        """Compare pricing across suppliers for similar materials"""
        products = (
            SupplierProduct.objects.filter(
                Q(product_name__icontains=material_query)
                | Q(parsed_description__icontains=material_query)
                | Q(specifications__icontains=material_query)
            )
            .select_related("supplier")
            .order_by("variant_price")
        )

        if not products:
            return f"No products found for '{material_query}'"

        results = [f"Price Comparison for '{material_query}':"]

        supplier_prices = {}
        for product in products:
            if product.variant_price:
                supplier_name = product.supplier.name
                if supplier_name not in supplier_prices:
                    supplier_prices[supplier_name] = []
                supplier_prices[supplier_name].append(
                    {
                        "product": product.product_name,
                        "price": float(product.variant_price),
                        "unit": product.price_unit or "each",
                        "url": product.url,
                    }
                )

        for supplier, products_list in supplier_prices.items():
            avg_price = sum(p["price"] for p in products_list) / len(products_list)
            results.append(f"\n• {supplier} (avg: ${avg_price:.2f}):")
            for product_info in products_list[:3]:  # Show top 3 products
                result = f"  - {product_info['product']}: ${product_info['price']:.2f} {product_info['unit']}"
                if product_info.get("url"):
                    result += f"\n    URL: {product_info['url']}"
                results.append(result)

        return "\n".join(results)

    def calc_sheet_tenths(
        self,
        part_width_mm: float,
        part_height_mm: float,
        sheet_width_mm: float = 1200.0,
        sheet_height_mm: float = 2400.0,
    ) -> str:
        """
        Calculate how many "tenths" of a sheet a part will occupy.

        A sheet is divided into a 5x2 grid (10 sections). For a standard 1200x2400mm
        sheet, each section is 600mm x 480mm. If any part of a cut touches a section,
        that section counts as used. This is used for quoting sheet material costs.

        Args:
            part_width_mm: Width of the part in millimeters
            part_height_mm: Height of the part in millimeters
            sheet_width_mm: Width of the full sheet (default: 1200mm)
            sheet_height_mm: Height of the full sheet (default: 2400mm)

        Returns:
            Formatted string with the calculation results

        Example:
            700mm x 700mm part on standard sheet = 4 tenths (spans 2x2 grid)
        """
        try:
            tenths = calculate_sheet_tenths(
                part_width_mm, part_height_mm, sheet_width_mm, sheet_height_mm
            )

            section_width = sheet_width_mm / 2
            section_height = sheet_height_mm / 5

            result = [
                "Sheet Tenths Calculation:",
                f"Part dimensions: {part_width_mm}mm × {part_height_mm}mm",
                f"Sheet dimensions: {sheet_width_mm}mm × {sheet_height_mm}mm",
                f"Section size: {section_width}mm × {section_height}mm",
                "",
                f"**Result: {tenths} tenths of a sheet required**",
                "",
                f"This part will span across {tenths} sections of the sheet grid.",
                f"Bill the customer for {tenths}/10ths of the sheet cost.",
            ]

            return "\n".join(result)

        except ValueError as e:
            return f"Error calculating sheet tenths: {str(e)}"
