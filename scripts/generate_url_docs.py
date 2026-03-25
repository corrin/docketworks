#!/usr/bin/env python3
"""
URL Documentation Auto-Generation Script

Usage: python scripts/generate_url_docs.py [--app APP_NAME]
"""

import argparse
import inspect
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Set up logging first
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def setup_django():
    """Setup Django environment with improved error handling."""
    try:
        # Set up Django environment
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")

        # Ensure we're in the right directory
        script_dir = Path(__file__).parent
        project_root = script_dir.parent
        os.chdir(project_root)

        # Add project root to Python path if not already there
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        import django

        # Configure Django with minimal settings that won't trigger app loading issues
        django.setup()

        from django.urls import URLPattern, URLResolver, get_resolver

        return URLPattern, URLResolver, get_resolver

    except ImportError as e:
        if "apps.quoting" in str(e):
            logger.error(f"Import error in apps.quoting: {e}")
            logger.error(
                "This might be caused by a circular import or missing dependency."
            )
            logger.error("Try running: python manage.py check --deploy")
        else:
            logger.error(f"Import error during Django setup: {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Failed to setup Django environment: {e}")
        logger.error("This script requires a properly configured Django environment.")
        logger.error(
            "Make sure you're running from the project root and database is accessible."
        )
        sys.exit(1)


# Setup Django and get required classes - but handle the import error
try:
    URLPattern, URLResolver, get_resolver = setup_django()
except SystemExit:
    # If Django setup fails, we still want to exit gracefully
    logger.error("Django setup failed. Exiting.")
    sys.exit(1)


class URLDocumentationGenerator:
    """Generates URL documentation from Django URL patterns."""

    def __init__(self):
        self.url_resolver = get_resolver()

    def extract_url_info(
        self, url_pattern: URLPattern, namespace: str = ""
    ) -> Optional[Dict[str, Any]]:
        """Extract information from URL pattern."""
        try:
            pattern = self._get_pattern_string(url_pattern)
            if not pattern:
                logger.warning("Could not extract pattern from URL")
                return None

            view_info = self._resolve_view_info(url_pattern)
            if not view_info:
                logger.warning(f"Could not resolve view for pattern: {pattern}")
                return None

            url_name = url_pattern.name
            if not url_name:
                # Only warn for non-admin URLs that should have names
                if not (
                    "django.contrib.admin" in view_info.get("module", "")
                    or "debug_toolbar" in view_info.get("module", "")
                    or view_info.get("function") in ["serve", "RedirectView"]
                ):
                    logger.warning(f"URL pattern has no name: {pattern}")
                url_name = "N/A"

            if namespace:
                url_name = f"{namespace}:{url_name}"

            description = self._extract_description(view_info)
            if not description:
                # Only warn for custom views that should have docstrings
                if not (
                    "django.contrib" in view_info.get("module", "")
                    or "debug_toolbar" in view_info.get("module", "")
                    or "rest_framework" in view_info.get("module", "")
                    or view_info.get("function") in ["serve", "shortcut"]
                ):
                    logger.warning(
                        f"No description found for: {pattern} -> {view_info['display_name']}"
                    )
                description = "No description available"

            # Check for functional group attribute, otherwise use app-based categorization
            functional_group = getattr(url_pattern, "functional_group", None)
            if functional_group:
                category = functional_group
            else:
                category = self._categorize_url(pattern, view_info, url_name)

            return {
                "pattern": pattern,
                "view": view_info["display_name"],
                "name": url_name,
                "description": description,
                "category": category,
                "is_api": pattern.startswith("/api/"),
            }

        except Exception as e:
            logger.warning(f"Failed to process URL pattern: {e}")
            return None

    def _get_pattern_string(self, url_pattern: URLPattern) -> Optional[str]:
        """Extract URL pattern string for documentation display.

        This function takes Django's internal URLPattern objects and converts them
        into human-readable URL patterns like:
        - `/api/autosave-job/`
        - `/job/<uuid:job_id>/`
        - `/timesheets/day/<str:date>/<uuid:staff_id>/`

        These patterns are displayed in the "URL Pattern" column of the generated
        documentation tables (see docs/urls/README.md for examples).

        Django stores URL patterns in different internal formats:
        - path() creates patterns with _route attribute (simple string matching)
        - re_path() creates patterns with _regex attribute (regex matching)

        This function extracts the pattern regardless of the internal format.
        """
        try:
            # Check if url_pattern has a pattern attribute
            if not hasattr(url_pattern, "pattern"):
                logger.warning(
                    f"URL pattern has no pattern attribute: {type(url_pattern)}"
                )
                return None

            pattern_obj = url_pattern.pattern

            # Handle case where pattern is already a string
            if isinstance(pattern_obj, str):
                if pattern_obj == "":
                    return "/"
                return "/" + pattern_obj.strip("/") + "/"

            # Handle route-based patterns (path() function)
            elif hasattr(pattern_obj, "_route"):
                route = pattern_obj._route
                if route == "":
                    return "/"
                return "/" + route.rstrip("/") + "/"

            # Handle regex-based patterns (re_path() function)
            elif hasattr(pattern_obj, "_regex"):
                regex_obj = pattern_obj._regex
                if hasattr(regex_obj, "pattern"):
                    regex = regex_obj.pattern
                else:
                    regex = str(regex_obj)
                if any(
                    char in regex
                    for char in ["(", ")", "[", "]", "+", "*", "?", "{", "}"]
                ):
                    logger.warning(f"Complex regex pattern: {regex}")
                clean = regex.replace("^", "").replace("$", "").replace("\\/", "/")
                return "/" + clean.rstrip("/") + "/"

            # Handle string patterns (fallback)
            else:
                pattern_str = str(pattern_obj)
                if pattern_str and pattern_str != "None":
                    return "/" + pattern_str.strip("/") + "/"

            logger.warning(f"Unknown pattern type: {type(pattern_obj)}")
            return None

        except Exception as e:
            logger.warning(
                f"Failed to extract pattern: {e} - URL pattern type: {type(url_pattern)}"
            )
            return None

    def _resolve_actual_view(self, view_func):
        """Unwrap decorators to get the actual view function."""
        # Handle __wrapped__ attribute (standard Python wrapping)
        if hasattr(view_func, "__wrapped__"):
            return self._resolve_actual_view(view_func.__wrapped__)

        # Handle Django's functools.wraps pattern where the original function
        # might be stored in different attributes
        if hasattr(view_func, "__name__") and view_func.__name__ == "_wrapped_view":
            # Look for the original function in closure variables
            if hasattr(view_func, "__closure__") and view_func.__closure__:
                for cell in view_func.__closure__:
                    if hasattr(cell.cell_contents, "__name__"):
                        return cell.cell_contents

        return view_func

    def _resolve_view_info(self, url_pattern: URLPattern) -> Optional[Dict[str, str]]:
        """Resolve view function information."""
        try:
            view_func = url_pattern.callback
            if not view_func:
                return None

            # Unwrap decorated views to get actual function
            actual_view_func = self._resolve_actual_view(view_func)

            if hasattr(view_func, "view_class"):
                view_class = view_func.view_class
                module_name = view_class.__module__
                class_name = view_class.__name__

                if "views" in module_name:
                    view_module = module_name.split(".")[-1]
                    display_name = f"{view_module}.{class_name}"
                else:
                    display_name = class_name

                return {
                    "module": module_name,
                    "function": class_name,
                    "display_name": display_name,
                    "view_object": view_class,
                }

            module_name = actual_view_func.__module__
            func_name = actual_view_func.__name__

            if "views" in module_name:
                view_module = module_name.split(".")[-1]
                display_name = f"{view_module}.{func_name}"
            else:
                display_name = func_name

            return {
                "module": module_name,
                "function": func_name,
                "display_name": display_name,
                "view_object": actual_view_func,
            }

        except Exception as e:
            logger.warning(f"Failed to resolve view: {e}")
            return None

    def _extract_description(self, view_info: Dict[str, str]) -> Optional[str]:
        """Extract description from docstring or comment."""
        try:
            view_object = view_info.get("view_object")
            if not view_object:
                return None

            # Special handling for built-in Django views
            description = self._get_builtin_view_description(view_info)
            if description:
                return description

            if hasattr(view_object, "__doc__") and view_object.__doc__:
                docstring = view_object.__doc__.strip()
                if docstring and not docstring.startswith('"""'):
                    first_line = docstring.split("\n")[0].strip()
                    if first_line and len(first_line) > 10:
                        return first_line

            comment = self._extract_comment_from_source(view_object)
            if comment:
                return comment

            return None

        except Exception:
            return None

    def _get_builtin_view_description(self, view_info: Dict[str, str]) -> Optional[str]:
        """Provide descriptions for built-in Django views."""
        display_name = view_info.get("display_name", "")
        function_name = view_info.get("function", "")
        module = view_info.get("module", "")

        # Django admin views
        if "django.contrib.admin" in module:
            admin_descriptions = {
                "add_view": "Django admin view for adding new model instances",
                "change_view": "Django admin view for editing existing model instances",
                "delete_view": "Django admin view for deleting model instances",
                "changelist_view": "Django admin view for listing model instances",
                "autocomplete_view": "Django admin autocomplete view for foreign key lookups",
                "history_view": "Django admin view showing change history for model instances",
                "app_index": "Django admin view showing all models for a specific app",
                "index": "Django admin main index page listing all installed apps",
            }
            if function_name in admin_descriptions:
                return admin_descriptions[function_name]

        # Django auth views
        if "django.contrib.auth" in module:
            auth_descriptions = {
                "PasswordResetView": "Django built-in view for initiating password reset",
                "PasswordResetDoneView": "Django built-in view shown after password reset email sent",
                "PasswordResetConfirmView": "Django built-in view for confirming password reset via email link",
                "PasswordResetCompleteView": "Django built-in view shown after successful password reset",
                "PasswordChangeDoneView": "Django built-in view shown after successful password change",
            }
            if function_name in auth_descriptions:
                return auth_descriptions[function_name]

        # Django static/media serving views
        if "django.views.static" in module:
            if function_name == "serve":
                return "Django built-in view for serving static files in development"

        # Django generic views
        if "django.views.generic" in module:
            generic_descriptions = {
                "RedirectView": "Django built-in view for HTTP redirects"
            }
            if function_name in generic_descriptions:
                return generic_descriptions[function_name]

        # Django debug toolbar views
        if "debug_toolbar" in module:
            debug_descriptions = {
                "render_panel": "Django Debug Toolbar view for rendering debug panels",
                "template_source": "Django Debug Toolbar view for showing template source code",
            }
            if function_name in debug_descriptions:
                return debug_descriptions[function_name]

        # Django REST Framework views
        if "rest_framework" in module:
            drf_descriptions = {
                "APIRootView": "Django REST Framework root API view listing available endpoints"
            }
            if function_name in drf_descriptions:
                return drf_descriptions[function_name]

        # Handle lambda functions (usually deprecated endpoints)
        if function_name == "<lambda>":
            # Check if this is a deprecated endpoint by looking at the display name
            if "deprecated" in display_name.lower():
                return "Deprecated endpoint returning HTTP 410 GONE status"
            else:
                return "Lambda function endpoint"

        return None

    def _extract_comment_from_source(self, view_object) -> Optional[str]:
        """Extract comment from source code above function."""
        try:
            source_file = inspect.getfile(view_object)
            source_lines, start_line = inspect.getsourcelines(view_object)

            with open(source_file, "r", encoding="utf-8") as f:
                all_lines = f.readlines()

            for i in range(max(0, start_line - 4), start_line - 1):
                if i < len(all_lines):
                    line = all_lines[i].strip()
                    if line.startswith("#") and len(line) > 5:
                        comment = line[1:].strip()
                        if comment and len(comment) > 10:
                            return comment

            return None

        except Exception:
            return None

    def _categorize_url(
        self, pattern: str, view_info: Dict[str, str], url_name: str
    ) -> str:
        """Hybrid categorization with path-based logic and override support."""

        # Script override mappings for special cases
        CATEGORY_OVERRIDES = {
            "view_kanban": "Kanban Board",
            "fetch_jobs": "Kanban Board",
            "home": "Main Redirect",
            "api_company_defaults": "System",
            "get_env_variable": "System",
            "get_enum_choices": "System",
            "login": "Authentication",
            "logout": "Authentication",
            "xero_sync_progress": "Xero Integration",
            "xero_index": "Xero Integration",
            "xero-error-list": "System",
            "xero-error-detail": "System",
        }

        # Check script overrides first
        clean_name = url_name.split(":")[-1]  # Remove namespace prefix
        if clean_name in CATEGORY_OVERRIDES:
            return CATEGORY_OVERRIDES[clean_name]

        # Special handling for admin URLs and generic patterns
        if (
            url_name.startswith("admin:")
            or "admin" in view_info.get("module", "").lower()
        ):
            return "Django Admin"

        # Handle generic patterns like //
        if pattern == "//" or pattern == "/":
            # Try to categorize by view info
            view_name = view_info.get("display_name", "").lower()
            if "admin" in view_name or "admin" in view_info.get("module", "").lower():
                return "Django Admin"
            elif url_name == "home":
                return "Main Redirect"
            else:
                return "Other"

        # Handle patterns with only parameters like /<path:object_id>/
        if pattern.count("/") >= 2 and all(
            seg.startswith("<") or seg == "" for seg in pattern.split("/")
        ):
            if "admin" in view_info.get("module", "").lower() or url_name.startswith(
                "admin:"
            ):
                return "Django Admin"
            else:
                return "Other"

        # Path-based categorization logic
        view_info.get("module", "").lower()
        pattern.lower()

        # Main redirect
        if pattern == "/":
            return "Main Redirect"

        # API endpoints get subcategorized by path hierarchy
        if pattern.startswith("/api/"):
            # Extract path segments, ignoring parameters like <uuid:job_id>
            segments = [
                seg for seg in pattern.split("/") if seg and not seg.startswith("<")
            ]

            if len(segments) >= 2:  # api + first_segment
                first_segment = segments[1].lower()

                # Generate category name dynamically
                category = first_segment.title() + " Management"

                # Sanity check for special cases
                if first_segment == "xero":
                    return "Xero Integration"
                elif first_segment == "reports" or first_segment == "report":
                    return "Reports"
                elif first_segment in [
                    "mcp",
                    "company-defaults",
                    "enums",
                    "get-env-variable",
                ]:
                    return "System"
                else:
                    return category
            else:
                return "System"

        # Non-API endpoints - use path hierarchy
        # Extract first path segment, ignoring parameters
        segments = [
            seg for seg in pattern.split("/") if seg and not seg.startswith("<")
        ]

        if len(segments) >= 1:
            first_segment = segments[0].lower()

            # Generate category name dynamically
            category = first_segment.title() + " Management"

            # Sanity check for special cases
            if first_segment == "kanban":
                return "Kanban Board"
            elif first_segment in ["reports", "report"]:
                return "Reports"
            elif first_segment in ["login", "logout"]:
                return "Authentication"
            elif first_segment == "__debug__":
                return "Development Tools"
            else:
                return category
        else:
            return "Other"

    def extract_all_urls(self, app_name: str = None) -> List[Dict[str, Any]]:
        """Extract all URL patterns."""
        urls = []

        def process_patterns(patterns, namespace=""):
            for pattern in patterns:
                if isinstance(pattern, URLResolver):
                    new_namespace = pattern.namespace
                    if namespace:
                        new_namespace = (
                            f"{namespace}:{new_namespace}"
                            if new_namespace
                            else namespace
                        )
                    else:
                        new_namespace = new_namespace or ""
                    process_patterns(pattern.url_patterns, new_namespace)

                elif isinstance(pattern, URLPattern):
                    if app_name:
                        view_info = self._resolve_view_info(pattern)
                        if not view_info or app_name not in view_info.get("module", ""):
                            continue

                    url_info = self.extract_url_info(pattern, namespace)
                    if url_info:
                        urls.append(url_info)

        process_patterns(self.url_resolver.url_patterns)
        return urls

    def generate_markdown_documentation(
        self, urls: List[Dict[str, Any]], app_name: str = None
    ) -> str:
        """Generate markdown documentation."""
        if app_name:
            title = f"# {app_name.title()} URLs Documentation"
        else:
            title = "# Generated URLs Documentation"

        content = [
            title,
            "",
            "<!-- This file is auto-generated. To regenerate, run: python scripts/generate_url_docs.py -->",
            "",
        ]

        # Split into API and non-API sections
        api_urls = [url for url in urls if url["is_api"]]
        other_urls = [url for url in urls if not url["is_api"]]

        # API Endpoints section
        if api_urls:
            content.extend(["## API Endpoints", ""])
            api_grouped = self._group_urls_by_category(api_urls)

            for category in sorted(api_grouped.keys()):
                content.extend(
                    [
                        f"#### {category}",
                        self._generate_url_table(api_grouped[category]),
                        "",
                    ]
                )

        # Other URLs section
        if other_urls:
            other_grouped = self._group_urls_by_category(other_urls)

            for category in sorted(other_grouped.keys()):
                content.extend(
                    [
                        f"### {category}",
                        self._generate_url_table(other_grouped[category]),
                        "",
                    ]
                )

        return "\n".join(content)

    def _group_urls_by_category(
        self, urls: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group URLs by category."""
        grouped = {}

        for url in urls:
            category = url["category"]
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(url)

        # Sort within each category by pattern
        for category in grouped:
            grouped[category].sort(key=lambda x: x["pattern"])

        return grouped

    def _generate_url_table(self, urls: List[Dict[str, Any]]) -> str:
        """Generate markdown table."""
        if not urls:
            return ""

        lines = [
            "| URL Pattern | View | Name | Description |",
            "|-------------|------|------|-------------|",
        ]

        urls.sort(key=lambda x: x["pattern"])

        for url in urls:
            pattern = url["pattern"].replace("|", "\\|")
            view = url["view"].replace("|", "\\|")
            name = url["name"].replace("|", "\\|")
            description = url["description"].replace("|", "\\|")

            lines.append(f"| `{pattern}` | `{view}` | `{name}` | {description} |")

        return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate URL documentation")
    parser.add_argument("--app", help="Generate for specific app only")
    parser.add_argument("--output", default="docs/urls/", help="Output directory")

    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    generator = URLDocumentationGenerator()

    if args.app:
        # Generate for specific app
        urls = generator.extract_all_urls(args.app)
        markdown_content = generator.generate_markdown_documentation(urls, args.app)
        output_file = output_dir / f"{args.app}.md"

        with open(output_file, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info(f"Generated documentation for {args.app} app: {output_file}")
    else:
        # Generate for all apps
        from django.apps import apps

        # Get all installed apps that are in the current project (not third-party)
        project_apps = []
        for app_config in apps.get_app_configs():
            app_name = app_config.name
            # Only include apps that are part of this project (start with 'apps.')
            if app_name.startswith("apps."):
                project_apps.append(
                    app_name.split(".")[1]
                )  # Extract app name from 'apps.appname'

        logger.info(f"Generating documentation for apps: {', '.join(project_apps)}")

        for app_name in project_apps:
            urls = generator.extract_all_urls(app_name)
            if urls:  # Only generate if there are URLs for this app
                markdown_content = generator.generate_markdown_documentation(
                    urls, app_name
                )
                output_file = output_dir / f"{app_name}.md"

                with open(output_file, "w", encoding="utf-8") as f:
                    f.write(markdown_content)
                logger.info(f"Generated documentation for {app_name}: {output_file}")
            else:
                logger.info(f"No URLs found for {app_name} app, skipping...")


if __name__ == "__main__":
    main()
