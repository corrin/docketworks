"""
Tests to ensure all API endpoints are covered by the OpenAPI schema.

This prevents developers from creating endpoints that bypass the schema,
which is the single source of truth for frontend-backend communication.
"""

import re

from django.test import TestCase
from django.urls import URLPattern, URLResolver, get_resolver
from drf_spectacular.generators import SchemaGenerator

# Endpoints that are intentionally excluded from the schema.
# Add a comment explaining why each is excluded.
ALLOWED_NON_SCHEMA_PATTERNS = {
    # Django admin
    "admin",
    # Debug toolbar
    "__debug__",
    # Schema/docs endpoints (they ARE the schema)
    "api/docs",
    "api/schema/",
    # OAuth redirects (not JSON APIs, browser redirects)
    "api/xero/oauth/callback/",
    "api/xero/authenticate/",
    # SSE streams (not REST, special protocol)
    "api/xero/sync-stream/",
    "api/timesheets/payroll/post-staff-week/stream/",
    # Webhooks (called by external services, not frontend)
    "api/xero/webhook/",
    # AWS instance management (internal ops, not frontend)
    "api/aws/",
    # Enum endpoint (internal, values embedded in schema)
    "api/enums/",
    # DRF router roots (meta-endpoints listing sub-routes, not real APIs)
    "api/workflow/",
    "api/clients/",
    "api/purchasing/",
    "api/quoting/",
    # Django template-based password change (not a JSON API)
    "api/accounts/password_change/",
    # App/Xero error endpoints (DRF browsable API, not frontend-consumed)
    "api/app-errors/",
    "api/rest/app-errors/",
    "api/xero-errors/",
    # Static/media files
    "static",
    "media",
}


class APISchemaComplianceTest(TestCase):
    """Ensure all API endpoints are documented in the OpenAPI schema."""

    def _get_all_url_patterns(self, resolver=None, prefix=""):
        """Recursively get all URL patterns."""
        if resolver is None:
            resolver = get_resolver()

        patterns = []
        for pattern in resolver.url_patterns:
            if isinstance(pattern, URLResolver):
                nested_prefix = prefix + str(pattern.pattern)
                patterns.extend(self._get_all_url_patterns(pattern, nested_prefix))
            elif isinstance(pattern, URLPattern):
                full_path = prefix + str(pattern.pattern)
                patterns.append(full_path)
        return patterns

    def _is_excluded(self, path: str) -> bool:
        """Check if path is in the exclusion list."""
        for allowed in ALLOWED_NON_SCHEMA_PATTERNS:
            if path.startswith(allowed):
                return True
        return False

    def _is_api_endpoint(self, path: str) -> bool:
        """Check if a path is an API endpoint that should be in the schema."""
        if not path.startswith("api/"):
            return False
        # Skip DRF auto-generated format suffix patterns
        if "<drf_format_suffix:format>" in path or ".(?P<format>" in path:
            return False
        # Skip DRF router regex patterns (covered by cleaner paths in schema)
        if "^" in path or "(?P<" in path:
            return False
        return not self._is_excluded(path)

    def _normalize_path(self, url_pattern: str) -> str:
        """Convert Django URL pattern to schema format."""
        # Remove regex anchors
        path = url_pattern.rstrip("$")
        # Convert <type:name> or <name> to {name}
        path = re.sub(r"<(?:\w+:)?(\w+)>", r"{\1}", path)
        # drf_spectacular renames {pk} to {id} in schema paths
        path = re.sub(r"\{pk\}", "{id}", path)
        # Normalize trailing slash
        return path.rstrip("/")

    def _get_schema_paths(self) -> set:
        """Get all paths from the OpenAPI schema."""
        generator = SchemaGenerator()
        schema = generator.get_schema(public=True)
        if schema and "paths" in schema:
            return {path.lstrip("/").rstrip("/") for path in schema["paths"].keys()}
        return set()

    def test_all_api_endpoints_in_schema(self):
        """Every API endpoint must be documented in the OpenAPI schema."""
        all_patterns = self._get_all_url_patterns()
        schema_paths = self._get_schema_paths()

        api_patterns = [p for p in all_patterns if self._is_api_endpoint(p)]

        missing_from_schema = []
        for pattern in api_patterns:
            normalized = self._normalize_path(pattern)
            if normalized not in schema_paths:
                missing_from_schema.append(pattern)

        if missing_from_schema:
            self.fail(
                "API endpoints not in OpenAPI schema (add @api_view and @extend_schema):\n"
                + "\n".join(f"  - {p}" for p in sorted(missing_from_schema))
            )
