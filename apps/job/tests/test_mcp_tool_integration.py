"""
Tests for MCP (Model Context Protocol) tool integration

Tests cover:
- QuotingTool functionality
- SupplierProductQueryTool functionality
- Tool parameter validation
- Error handling in tool execution
"""

from apps.client.models import Client
from apps.job.models import Job
from apps.quoting.mcp import QuotingTool, SupplierProductQueryTool
from apps.quoting.models import SupplierPriceList, SupplierProduct
from apps.testing import BaseTestCase


class QuotingToolTests(BaseTestCase):
    """Test QuotingTool functionality"""

    def setUp(self):
        """Set up test data"""
        # Create a supplier
        self.supplier = Client.objects.create(
            name="ABC Steel",
            email="sales@abcsteel.com",
            is_supplier=True,
            xero_last_modified="2024-01-01T00:00:00Z",
        )

        # Create another supplier for comparison tests
        self.supplier2 = Client.objects.create(
            name="XYZ Metals",
            email="sales@xyzmetals.com",
            is_supplier=True,
            xero_last_modified="2024-01-01T00:00:00Z",
        )

        # Create a client for job tests
        self.client_obj = Client.objects.create(
            name="Test Client",
            email="client@example.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )

        # Create price lists
        self.price_list = SupplierPriceList.objects.create(
            supplier=self.supplier,
            file_name="test_prices.pdf",
        )
        self.price_list2 = SupplierPriceList.objects.create(
            supplier=self.supplier2,
            file_name="test_prices2.pdf",
        )

        # Create test products
        self.product1 = SupplierProduct.objects.create(
            supplier=self.supplier,
            price_list=self.price_list,
            product_name="Steel Angle 50x50x5",
            description="Hot rolled steel angle",
            item_no="SA-50-5",
            variant_id="SA-50-5-V1",
            variant_price="5.50",
            price_unit="per metre",
            parsed_metal_type="steel",
            url="https://abcsteel.com/angle",
        )

        self.product2 = SupplierProduct.objects.create(
            supplier=self.supplier,
            price_list=self.price_list,
            product_name="Steel Plate 6mm",
            description="Hot rolled steel plate 6mm thick",
            item_no="SP-6",
            variant_id="SP-6-V1",
            variant_price="125.00",
            price_unit="per sheet",
            parsed_metal_type="steel",
            parsed_dimensions="1200x2400",
        )

        self.product3 = SupplierProduct.objects.create(
            supplier=self.supplier2,
            price_list=self.price_list2,
            product_name="Aluminum Sheet 3mm",
            description="Aluminum alloy sheet",
            item_no="AS-3",
            variant_id="AS-3-V1",
            variant_price="89.00",
            price_unit="per sheet",
            parsed_metal_type="aluminum",
        )

        self.product4 = SupplierProduct.objects.create(
            supplier=self.supplier2,
            price_list=self.price_list2,
            product_name="Steel Angle 40x40x4",
            description="Mild steel angle",
            item_no="SA-40-4",
            variant_id="SA-40-4-V1",
            variant_price="4.25",
            price_unit="per metre",
            parsed_metal_type="steel",
        )

        self.job = Job.objects.create(
            name="Test Job",
            description="Test job description",
            client=self.client_obj,
            status="quoting",
            staff=self.test_staff,
        )

        self.tool = QuotingTool()

    def test_tool_initialization(self):
        """Test tool initializes correctly"""
        self.assertIsInstance(self.tool, QuotingTool)

    def test_search_products_basic(self):
        """Test basic product search functionality"""
        result = self.tool.search_products(query="steel")

        self.assertIn("Steel Angle", result)
        self.assertIn("Steel Plate", result)
        self.assertIn("ABC Steel", result)

    def test_search_products_with_supplier(self):
        """Test product search with supplier filter"""
        result = self.tool.search_products(query="steel", supplier_name="ABC Steel")

        self.assertIn("ABC Steel", result)
        self.assertNotIn("XYZ Metals", result)

    def test_search_products_no_results(self):
        """Test product search with no results"""
        result = self.tool.search_products(query="nonexistent_material_xyz")

        self.assertIn("No products found", result)

    def test_search_products_case_insensitive(self):
        """Test that product search is case insensitive"""
        result = self.tool.search_products(query="STEEL ANGLE")

        self.assertIn("Steel Angle", result)

    def test_get_pricing_for_material(self):
        """Test getting pricing for specific material"""
        result = self.tool.get_pricing_for_material(material_type="steel")

        self.assertIn("steel", result.lower())
        self.assertIn("ABC Steel", result)

    def test_get_pricing_with_dimensions(self):
        """Test getting pricing with dimensions filter"""
        result = self.tool.get_pricing_for_material(
            material_type="steel", dimensions="1200x2400"
        )

        self.assertIn("1200x2400", result)

    def test_get_pricing_no_results(self):
        """Test getting pricing with no matching materials"""
        result = self.tool.get_pricing_for_material(material_type="titanium")

        self.assertIn("No pricing found", result)

    def test_create_quote_estimate(self):
        """Test creating a quote estimate"""
        result = self.tool.create_quote_estimate(
            job_id=str(self.job.id),
            materials="Steel angle, steel plate",
            labor_hours=15,
        )

        self.assertIn(self.job.name, result)
        self.assertIn(self.client_obj.name, result)
        self.assertIn("Labor estimate", result)
        self.assertIn("15", result)

    def test_create_quote_estimate_invalid_job(self):
        """Test creating quote for non-existent job"""
        result = self.tool.create_quote_estimate(
            job_id="00000000-0000-0000-0000-000000000000",
            materials="Steel angle",
        )

        self.assertIn("not found", result)

    def test_get_supplier_status(self):
        """Test getting supplier status"""
        result = self.tool.get_supplier_status()

        self.assertIn("ABC Steel", result)
        self.assertIn("XYZ Metals", result)
        self.assertIn("Products:", result)

    def test_get_supplier_status_filtered(self):
        """Test getting supplier status with filter"""
        result = self.tool.get_supplier_status(supplier_name="ABC")

        self.assertIn("ABC Steel", result)

    def test_compare_suppliers(self):
        """Test comparing suppliers for same material"""
        result = self.tool.compare_suppliers(material_query="steel angle")

        self.assertIn("ABC Steel", result)
        self.assertIn("XYZ Metals", result)
        self.assertIn("Comparison", result)

    def test_compare_suppliers_no_results(self):
        """Test comparing suppliers with no matching products"""
        result = self.tool.compare_suppliers(material_query="nonexistent_xyz")

        self.assertIn("No products found", result)

    def test_calc_sheet_tenths_basic(self):
        """Test basic sheet tenths calculation"""
        result = self.tool.calc_sheet_tenths(
            part_width_mm=600,
            part_height_mm=480,
        )

        self.assertIn("1 tenth", result.lower())
        self.assertIn("600", result)
        self.assertIn("480", result)

    def test_calc_sheet_tenths_larger_part(self):
        """Test sheet tenths for larger part spanning multiple sections"""
        result = self.tool.calc_sheet_tenths(
            part_width_mm=700,
            part_height_mm=700,
        )

        self.assertIn("4 tenth", result.lower())

    def test_calc_sheet_tenths_custom_sheet_size(self):
        """Test sheet tenths with custom sheet dimensions"""
        result = self.tool.calc_sheet_tenths(
            part_width_mm=500,
            part_height_mm=500,
            sheet_width_mm=1000,
            sheet_height_mm=2000,
        )

        self.assertIn("Sheet dimensions: 1000", result)
        self.assertIn("2000", result)


class SupplierProductQueryToolTests(BaseTestCase):
    """Test SupplierProductQueryTool functionality"""

    def setUp(self):
        """Set up test data"""
        self.supplier = Client.objects.create(
            name="Test Supplier",
            email="supplier@test.com",
            is_supplier=True,
            xero_last_modified="2024-01-01T00:00:00Z",
        )

        self.price_list = SupplierPriceList.objects.create(
            supplier=self.supplier,
            file_name="test.pdf",
        )

        self.product = SupplierProduct.objects.create(
            supplier=self.supplier,
            price_list=self.price_list,
            product_name="Test Product",
            item_no="TP-001",
            variant_id="TP-001-V1",
            variant_price="10.00",
        )

        self.tool = SupplierProductQueryTool()

    def test_tool_initialization(self):
        """Test tool initializes correctly"""
        self.assertIsInstance(self.tool, SupplierProductQueryTool)

    def test_model_attribute(self):
        """Test that model is set to SupplierProduct"""
        self.assertEqual(self.tool.model, SupplierProduct)

    def test_exclude_fields(self):
        """Test that supplier and price_list are excluded"""
        self.assertIn("supplier", self.tool.exclude_fields)
        self.assertIn("price_list", self.tool.exclude_fields)

    def test_get_queryset(self):
        """Test that get_queryset returns products with related data"""
        queryset = self.tool.get_queryset()
        product = queryset.first()

        # Should have prefetched the supplier
        self.assertEqual(product.supplier.name, "Test Supplier")


class MCPToolIntegrationTests(BaseTestCase):
    """Test MCP tool integration behavior"""

    def setUp(self):
        """Set up test data"""
        self.supplier = Client.objects.create(
            name="Integration Test Supplier",
            email="int@test.com",
            is_supplier=True,
            xero_last_modified="2024-01-01T00:00:00Z",
        )

        self.client_obj = Client.objects.create(
            name="Test Client",
            email="client@test.com",
            xero_last_modified="2024-01-01T00:00:00Z",
        )

        self.job = Job.objects.create(
            name="Integration Test Job",
            client=self.client_obj,
            status="quoting",
            staff=self.test_staff,
        )

    def test_tool_parameter_validation(self):
        """Test tool parameter validation"""
        tool = QuotingTool()

        # Test missing required parameters
        with self.assertRaises(TypeError):
            tool.search_products()  # Missing query parameter

    def test_tool_response_is_string(self):
        """Test that tools return string responses"""
        tool = QuotingTool()

        result = tool.search_products(query="test")

        # Response should be a string (required for MCP integration)
        self.assertIsInstance(result, str)
        self.assertGreater(len(result), 0)

    def test_tool_handles_special_characters(self):
        """Test that tools handle special characters in queries"""
        tool = QuotingTool()

        # Should not raise exception
        result = tool.search_products(query="steel & aluminum 50%")
        self.assertIsInstance(result, str)

    def test_tool_handles_empty_query(self):
        """Test that tools handle empty queries gracefully"""
        tool = QuotingTool()

        result = tool.search_products(query="")
        self.assertIsInstance(result, str)


class CalcSheetTenthsTests(BaseTestCase):
    """Dedicated tests for calc_sheet_tenths functionality"""

    def setUp(self):
        """Set up test tool"""
        self.tool = QuotingTool()

    def test_single_section(self):
        """Test part that fits in one section"""
        result = self.tool.calc_sheet_tenths(
            part_width_mm=500,
            part_height_mm=400,
        )
        self.assertIn("1 tenth", result.lower())

    def test_two_sections_horizontal(self):
        """Test part spanning two sections horizontally"""
        result = self.tool.calc_sheet_tenths(
            part_width_mm=700,  # > 600, spans 2 columns
            part_height_mm=400,  # fits in 1 row
        )
        self.assertIn("2 tenth", result.lower())

    def test_two_sections_vertical(self):
        """Test part spanning two sections vertically"""
        result = self.tool.calc_sheet_tenths(
            part_width_mm=500,  # fits in 1 column
            part_height_mm=500,  # > 480, spans 2 rows
        )
        self.assertIn("2 tenth", result.lower())

    def test_four_sections(self):
        """Test part spanning 2x2 sections"""
        result = self.tool.calc_sheet_tenths(
            part_width_mm=700,
            part_height_mm=700,
        )
        self.assertIn("4 tenth", result.lower())

    def test_full_sheet(self):
        """Test part using entire sheet"""
        result = self.tool.calc_sheet_tenths(
            part_width_mm=1200,
            part_height_mm=2400,
        )
        self.assertIn("10 tenth", result.lower())

    def test_oversized_part(self):
        """Test part larger than sheet"""
        result = self.tool.calc_sheet_tenths(
            part_width_mm=1500,
            part_height_mm=3000,
        )
        # Should handle gracefully - still returns a result
        self.assertIn("tenth", result.lower())
