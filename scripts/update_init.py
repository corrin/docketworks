import argparse
import ast
import glob
import logging
import os
import re
import sys


def get_import_type(module_path: str, module_name: str) -> str:
    """
    Determine how a module should be imported based on Django startup rules.

    Returns:
    - 'safe': Import directly (safe during Django startup)
    - 'conditional': Import only when Django is ready
    - 'excluded': Don't import in __init__.py, require explicit imports

    Rules:
    - Safe: apps, urls, enums, exceptions, constants, safe views
    - Conditional: admin, serializers, forms, managers, services, models (in main app init)
    - Excluded: views/modules with problematic Django auth imports
    """
    # NEVER conditional - these are required during Django startup
    # NOTE: 'views' is NOT in this list because it needs special analysis
    always_safe_modules = {"apps", "urls", "enums", "exceptions", "constants"}

    # ALWAYS excluded - these should not be imported in __init__.py
    # Django automatically discovers these modules
    always_excluded_modules = {
        "admin",  # Django auto-discovers admin.py, importing causes double registration
        "views",  # URL routing imports views directly when needed
    }

    # ALWAYS conditional - these definitely import models or problematic Django components
    # NOTE: models must be non-conditional as Django needs them during startup
    always_conditional_modules = {
        "serializers",
        "forms",
        "managers",
        "services",
        "authentication",
        "permissions",
    }

    # Models need special handling:
    # - Individual model files in models/ directories are safe
    # - But model imports in main app __init__.py should be conditional
    # - Django discovers models automatically by scanning directories
    if "/models/" in module_path:
        # This is a file inside a models directory - safe
        return "safe"
    elif module_name == "models":
        # This is importing models.py in a main app __init__.py - conditional
        return "conditional"

    # Check module name patterns first
    if module_name in always_safe_modules:
        return "safe"

    if module_name in always_excluded_modules:
        return "excluded"

    # Views need special analysis for problematic imports
    if (
        module_name.endswith("_view")
        or module_name.endswith("_views")
        or module_name == "views"
    ):
        # Check if this view file imports problematic auth components
        try:
            # encoding="utf-8" tells Python “assume the file is UTF-8” (which our repo is).
            # errors="ignore" (or "replace") silently drops (or replaces) any byte sequences that don’t make sense under UTF-8, so we still get roughly the right AST structure without the parser bombing out.
            with open(module_path, "r", encoding="utf-8", errors="ignore") as file:
                content = file.read()

            # Check for problematic auth imports that cause circular imports
            problematic_imports = [
                "from django.contrib.auth.mixins import",
                "from django.contrib.auth.decorators import",
                "from django.contrib.auth.forms import",
            ]

            for problematic in problematic_imports:
                if problematic in content:
                    return "excluded"  # Exclude from __init__.py entirely

        except Exception:
            logging.warning(
                f"Could not read {module_path} to check for problematic imports"
            )

        # Safe views go in __init__.py as non-conditional
        return "safe"

    if module_name in always_conditional_modules:
        return "conditional"

    # For other modules, analyze their imports
    try:
        with open(module_path, "r", encoding="utf-8", errors="ignore") as file:
            content = file.read()

        # Parse imports to detect problematic patterns
        tree = ast.parse(content)

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.ImportFrom):
                    module = node.module
                    if module:
                        # Check for model imports from Django apps
                        if re.match(r"^apps\.\w+\.models", module):
                            return "conditional"

                        # Check for Django model imports
                        if "django.contrib.auth.models" in module:
                            return "conditional"
                        if "django.db.models" in module:
                            return "conditional"

                        # Check for DRF imports that trigger settings loading
                        if module.startswith("rest_framework"):
                            return "conditional"

                        # Check for Django imports that require apps to be loaded
                        django_problematic_imports = [
                            "django.contrib.admin",
                            "django.contrib.auth",  # This includes mixins, decorators, forms
                            "django.forms",
                        ]
                        if any(
                            module.startswith(imp) for imp in django_problematic_imports
                        ):
                            return "conditional"

                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        # Check for problematic Django imports
                        django_problematic_direct = [
                            "django.contrib.admin",
                            "django.contrib.auth",
                            "django.forms",
                        ]
                        if any(
                            alias.name.startswith(imp)
                            for imp in django_problematic_direct
                        ):
                            return "conditional"

        # If we can't determine, default to safe for utils/helpers
        # but conditional for anything else
        safe_patterns = ["util", "helper", "constant", "enum", "exception"]
        if any(pattern in module_name.lower() for pattern in safe_patterns):
            # But only if they don't actually import models (checked above)
            return "safe"

        # Default to conditional for unknown modules to be safe
        return "conditional"

    except Exception:
        # If we can't parse the file, default to conditional to be safe
        return "conditional"


def generate_django_safe_imports(import_data):
    """Generate import statements that are safe during Django startup."""
    import_lines = [
        "# This file is autogenerated by update_init.py script",
        "",
    ]

    # Sort imports and separate into three categories
    import_data.sort(key=lambda x: x[0])
    safe_imports = []
    conditional_imports = []
    excluded_imports = []

    for module_name, exports, import_type in import_data:
        # Sort exports within each module
        sorted_exports = sorted(set(exports))  # Remove duplicates and sort
        if import_type == "safe":
            safe_imports.append((module_name, sorted_exports))
        elif import_type == "conditional":
            conditional_imports.append((module_name, sorted_exports))
        elif import_type == "excluded":
            excluded_imports.append((module_name, sorted_exports))

    # Generate safe imports first (always imported)
    for module_name, exports in safe_imports:
        # Use multi-line imports only if the line would be too long
        single_line = f"from .{module_name} import {', '.join(exports)}"
        if len(single_line) > 88:  # Black's default line length
            import_lines.append(f"from .{module_name} import (")
            for export in exports:
                import_lines.append(f"    {export},")
            import_lines.append(")")
        else:
            import_lines.append(single_line)

    # Generate conditional imports if any
    if conditional_imports:
        if safe_imports:  # Add spacing if we had safe imports
            import_lines.append("")
        import_lines.extend(
            [
                "# Conditional imports (only when Django is ready)",
                "try:",
                "    from django.apps import apps",
                "",
                "    if apps.ready:",
            ]
        )

        for module_name, exports in conditional_imports:
            # Use multi-line imports only if the line would be too long
            single_line = f"        from .{module_name} import {', '.join(exports)}"
            if len(single_line) > 88:  # Black's default line length
                import_lines.append(f"        from .{module_name} import (")
                for export in exports:
                    import_lines.append(f"            {export},")
                import_lines.append("        )")
            else:
                import_lines.append(single_line)

        import_lines.extend(
            [
                "except (ImportError, RuntimeError):",
                "    # Django not ready or circular import, skip conditional imports",
                "    pass",
            ]
        )

    # Add excluded imports section with documentation
    if excluded_imports:
        if safe_imports or conditional_imports:
            import_lines.append("")
        import_lines.extend(
            [
                "# EXCLUDED IMPORTS - These contain problematic dependencies that cause circular imports",
                "# Import these directly where needed using:",
            ]
        )

        for module_name, exports in excluded_imports:
            for export in exports:
                import_lines.append(f"# from .{module_name} import {export}")

        import_lines.append("#")

    return import_lines


def update_empty_init_py(target_dir: str, verbose: bool = False) -> int:
    """
    Creates an empty __init__.py file for directories that need it.
    Used for test directories and the apps directory.
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Creating empty init for: {target_dir}")

    init_file = os.path.join(target_dir, "__init__.py")

    content = "# This file is autogenerated by update_init.py script\n"

    try:
        with open(init_file, "w") as f:
            f.write(content)
        logger.info(f"Successfully updated init: {init_file}")
        return 0
    except IOError as e:
        logger.error(f"Failed to write to {init_file}: {e}")
        return 4


def update_init_py(target_dir: str, verbose: bool = False) -> int:
    logger = logging.getLogger(__name__)

    # Add file logging for debugging
    log_file = "logs/update_init_debug.log"
    file_handler = logging.FileHandler(log_file, mode="a")
    file_handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger.info(f"=== Starting update_init_py for {target_dir} ===")

    # Normalize target_dir path for cross-platform compatibility
    target_dir = os.path.normpath(target_dir)
    logger.debug(f"Normalized target_dir: {target_dir}")

    # Special handling for test directories - use empty init files
    if os.path.basename(target_dir) == "tests":
        return update_empty_init_py(target_dir, verbose)

    # Special handling for apps directory - just needs empty init
    if os.path.basename(target_dir) == "apps":
        return update_empty_init_py(target_dir, verbose)

    logger.debug(f"target_dir ends with 'models': {target_dir.endswith('models')}")
    logger.debug(
        f"target_dir contains apps sep: {os.path.sep + 'apps' + os.path.sep in target_dir}"
    )

    # Special exclusion for models directories inside apps (should be handled manually)
    if target_dir.endswith("models") and (
        os.path.sep + "apps" + os.path.sep in target_dir
        or target_dir.startswith("apps" + os.path.sep)
    ):
        logger.info(
            f"Skipping models directory (requires manual handling): {target_dir}"
        )
        return 0  # Success, but skipped

    # Special exclusion for migrations directories (Django auto-discovery)
    if (
        target_dir.endswith("migrations")
        or os.path.basename(target_dir) == "migrations"
    ):
        logger.info(
            f"Skipping migrations directory (Django auto-discovery): {target_dir}"
        )
        return 0  # Success, but skipped

    # Files/directories to exclude from auto-generation
    EXCLUDED_PATHS = {
        os.path.normpath("docketworks/settings/__init__.py"),
        os.path.normpath("docketworks/__init__.py"),  # Main project init
    }

    # Directories that should never have their __init__.py modified
    EXCLUDED_DIRECTORY_PATTERNS = [
        "migrations",
        "management" + os.sep + "commands",
        "__pycache__",
        "settings",  # Django settings directory
        "venv",  # Virtual environment
        ".venv",  # Alternative venv name
        "env",  # Alternative env name
        ".env",  # Alternative env name
        "node_modules",  # Node.js dependencies
        ".git",  # Git directory
        "logs",  # Log directory
    ]

    # Check if this is an excluded directory type
    for pattern in EXCLUDED_DIRECTORY_PATTERNS:
        # Check if the pattern appears anywhere in the path
        if pattern in target_dir.split(os.sep):
            logger.info(
                f"Skipping excluded directory pattern '{pattern}': {target_dir}"
            )
            return 0  # Success, but skipped

        # Also check the full path contains the pattern
        if pattern in target_dir:
            logger.info(
                f"Skipping excluded directory pattern '{pattern}': {target_dir}"
            )
            return 0  # Success, but skipped

    # Additional exclusion for the main docketworks directory itself
    if os.path.basename(target_dir) == "docketworks" and target_dir.endswith(
        "docketworks"
    ):
        os.path.dirname(target_dir)
        # Check if this is the main project directory (not an app named docketworks)
        if os.path.exists(os.path.join(target_dir, "settings")) and os.path.exists(
            os.path.join(target_dir, "wsgi.py")
        ):
            logger.info(f"Skipping main Django project directory: {target_dir}")
            return 0  # Success, but skipped

    init_file = os.path.join(target_dir, "__init__.py")

    # Check if this file should be excluded
    relative_init_path = os.path.normpath(os.path.relpath(init_file))
    if relative_init_path in EXCLUDED_PATHS:
        logger.info(f"Skipping excluded file: {relative_init_path}")
        return 0  # Success, but skipped

    if not os.path.exists(target_dir):
        logger.error(f"Skipping non-existent folder: {target_dir}")
        return 2  # Error Code 2: Directory does not exist

    py_files = [
        f for f in os.listdir(target_dir) if f.endswith(".py") and f != "__init__.py"
    ]

    if not py_files:
        logger.warning(
            f"No Python files found in {target_dir}. Skipping __init__.py generation."
        )
        return 0  # Success - no files to process is not an error

    all_exports = []
    import_data = []  # Store (module_name, exports, is_conditional)

    for py_file in py_files:
        module_name = py_file.replace(".py", "")
        module_path = os.path.join(target_dir, py_file)

        logger.debug(f"Processing file: {module_path}")

        # Determine how module should be imported based on what it imports
        import_type = get_import_type(module_path, module_name)

        # Parse the file to find class and function definitions
        try:
            with open(module_path, "r", encoding="utf-8", errors="ignore") as file:
                content = file.read()
                logger.debug(f"Successfully read {module_path}, length: {len(content)}")
                # Parse with explicit feature version to ensure match statement support
                tree = ast.parse(content, filename=module_path, mode="exec")
                logger.debug(f"Successfully parsed AST for {module_path}")
        except Exception as e:
            logger.error(f"Error parsing {module_path}: {e}")
            continue

        # Only get top-level classes, not nested classes
        classes = [
            node.name
            for node in tree.body  # Only top-level nodes
            if isinstance(node, ast.ClassDef)
            and node.name != "Meta"  # Exclude Meta class
        ]

        # Only get top-level functions, not class methods
        functions = [
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and not node.name.startswith("_")  # Exclude private functions
        ]

        exports = classes + functions
        exports = list(
            dict.fromkeys(exports)
        )  # Remove duplicates while preserving order
        logger.debug(
            f"Module {module_name}: classes={classes}, functions={functions}, import_type={import_type}"
        )
        if exports:
            logger.debug(f"Found classes: {classes}")
            logger.debug(f"Found functions: {functions}")
            import_data.append((module_name, exports, import_type))
            # Only add to __all__ if not excluded
            if import_type != "excluded":
                all_exports.extend(exports)
        else:
            logger.debug(f"No exports found in {module_name}")

    # Generate Django-safe import statements
    import_lines = generate_django_safe_imports(import_data)

    # Add __all__ definition - remove duplicates, sort alphabetically, and use double quotes
    unique_exports = sorted(set(all_exports))
    import_lines.append("")
    if unique_exports:
        import_lines.append("__all__ = [")
        for export_name in unique_exports:
            import_lines.append(f'    "{export_name}",')
        import_lines.append("]")
    else:
        import_lines.append("__all__ = []")

    # Prepare new text (LF-based)
    new_text = "\n".join(import_lines) + "\n"

    # Read existing bytes (if any)
    try:
        with open(init_file, "rb") as f:
            existing = f.read()
    except FileNotFoundError:
        existing = None

    # Detect existing newline style and re-encode new_text to bytes
    if existing and b"\r\n" in existing:
        new_bytes = new_text.replace("\n", "\r\n").encode("utf-8")
    else:
        new_bytes = new_text.encode("utf-8")

    # If nothing changed, skip writing
    if existing == new_bytes:
        logger.debug(f"No changes in {init_file}; skipping write")
        return 0

    # Otherwise write the updated file
    try:
        with open(init_file, "wb") as init_f:
            init_f.write(new_bytes)
        logger.info(f"Successfully updated {init_file}")
        return 0  # Success
    except IOError as e:
        logger.error(f"Failed to write to {init_file}: {e}")
        return 4


def find_all_init_directories() -> list[str]:
    """Find all directories containing __init__.py files, excluding problematic directories."""
    init_files = glob.glob("**/__init__.py", recursive=True)
    directories = [os.path.dirname(init_file) for init_file in init_files]

    # Filter out directories that should never be processed
    GLOBAL_EXCLUDED_PATTERNS = [
        "migrations",
        "management" + os.sep + "commands",
        "__pycache__",
        "venv",
        ".venv",
        "env",
        ".env",
        "node_modules",
        ".git",
        "logs",
    ]

    filtered_directories = []
    for directory in directories:
        should_exclude = False
        normalized_dir = os.path.normpath(directory)

        # Check if any excluded pattern appears in the directory path
        for pattern in GLOBAL_EXCLUDED_PATTERNS:
            if pattern in normalized_dir.split(os.sep):
                should_exclude = True
                break
            if pattern in normalized_dir:
                should_exclude = True
                break

        # Special check for main Django project directory
        if os.path.basename(
            normalized_dir
        ) == "docketworks" and normalized_dir.endswith("docketworks"):
            if os.path.exists(
                os.path.join(normalized_dir, "settings")
            ) and os.path.exists(os.path.join(normalized_dir, "wsgi.py")):
                should_exclude = True

        # Special check for models directories in apps
        if normalized_dir.endswith("models") and (
            os.path.sep + "apps" + os.path.sep in normalized_dir
            or normalized_dir.startswith("apps" + os.path.sep)
        ):
            should_exclude = True

        # Special check for migrations directories (Django auto-discovery)
        if (
            normalized_dir.endswith("migrations")
            or os.path.basename(normalized_dir) == "migrations"
        ):
            should_exclude = True

        if not should_exclude:
            filtered_directories.append(directory)

    return filtered_directories


def update_all_init_files(verbose: bool = False) -> int:
    """Update all __init__.py files found in the project."""
    logger = logging.getLogger(__name__)

    directories = find_all_init_directories()
    logger.info(f"Found {len(directories)} directories with __init__.py files")

    total_errors = 0
    success_count = 0

    for directory in directories:
        logger.info(f"Processing: {directory}")
        result = update_init_py(directory, verbose=verbose)
        if result == 0:
            success_count += 1
        else:
            total_errors += 1

    logger.info(f"Completed: {success_count} successful, {total_errors} errors")
    return total_errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Automatically update __init__.py with class imports"
    )
    parser.add_argument(
        "target_directory",
        nargs="?",
        help="Directory to process for generating imports in __init__.py (optional - defaults to all)",
    )
    parser.add_argument("--verbose", action="store_true", help="Enable verbose output")
    parser.add_argument(
        "--all", action="store_true", help="Update all __init__.py files in the project"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # If no target directory is provided, or --all is specified, update all
    if args.target_directory is None or args.all:
        result = update_all_init_files(verbose=args.verbose)
        sys.exit(result)
    else:
        result = update_init_py(args.target_directory, verbose=args.verbose)
        sys.exit(result)


if __name__ == "__main__":
    main()
