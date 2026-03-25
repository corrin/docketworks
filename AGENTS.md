# AGENTS.md

Authoritative guidance for AI coding agents working in the DocketWorks backend. Rules are distilled from `CLAUDE.md`, `.kilocode/rules/*.md`, and project readmes.

## Mission Context

- Morris Sheetmetal relies on this Django 5.x + DRF system to digitize quote -> production -> invoicing workflows. Business expectations live in `docs/README.md`.
- Backend agents own persistence, business logic, integrations, and REST APIs. Frontend/UI responsibilities live in the separate Vue + Django-templates project.

## Development Commands

```bash
# Environment setup
poetry shell
poetry install

# Run backend locally
python manage.py runserver 0.0.0.0:8000
python manage.py runserver_with_ngrok  # When Xero webhooks/tunnel are needed

# Quality commands
tox -e format        # Black + isort
tox -e lint
tox -e typecheck
tox                  # Runs full tox suite

# Database & data
python manage.py migrate
python manage.py loaddata apps/workflow/fixtures/company_defaults.json
python manage.py loaddata apps/workflow/fixtures/initial_data.json  # or backport_data_restore

# Integrations & schedulers
python manage.py xero --setup
python manage.py start_xero_sync
python manage.py run_scheduler         # APScheduler background jobs
```

## Core Engineering Principles

- **Fail early:** guard unhappy paths first and never add silent fallbacks.
- **Persist every exception** with `persist_app_error(exc, ...)`, then re-raise.
- Use the `Job -> CostSet -> CostLine` architecture with JSON `ext_refs` for external references and `meta` for entry-specific data.
- Keep business rules inside services; keep views and serializers lean.
- Maintain UUID primary keys, SimpleHistory auditing, and soft deletes where the models require them.

## Architecture Snapshot

- `workflow`: core models (CompanyDefaults, XeroAccount, AIProvider), authentication middleware, URL coordination, error persistence helpers.
- `job`: job lifecycle, Kanban statuses, CostSet/CostLine costing, JobEvent audit trail.
- `accounts`: custom Staff model, password policy (min length 10), role-based permissions.
- `client`: CRM and bidirectional Xero contact sync.
- `timesheet`: time tracking using CostLine with `kind='time'` and staff references in `meta`.
- `purchasing`: purchase orders, stock management, and Xero integration linked to CostLine via `ext_refs`.
- `accounting`: KPI dashboards, invoice reporting.
- `quoting`: quote generation, supplier price management, AI/Gemini extraction.

## Frontend / Backend Separation

- Backend: persistence, business logic, validation, authentication, external integrations, serialization of real data.
- Forbidden on the backend: static UI constants, HTML payloads, presentation concerns, or business decisions intended for the frontend.
- Frontend (Vue/templates): rendering, UX, routing, client-side form feedback, display-only constants.

## Code Organization Rules

- All Django apps live under `apps/`; mirror the existing structure of `models/`, `views/`, `services/`, `serializers/`, `api/`, and `tests/`.
- **Never edit `__init__.py` manually**—run `python scripts/update_init.py` after adding or removing modules.
- Use snake_case for modules/functions, PascalCase for classes, keep files short and cohesive, and prefer composition over inheritance.

## API Design Standards

- RESTful, plural, kebab-case URLs (`/api/jobs/`, `/api/jobs/{id}/cost-sets/`).
- Use standard HTTP verbs and DRF status codes (200, 201, 204, 400, 401, 403, 404, 409, 422, 500).
- Serialize responses with DRF serializers; include pagination metadata (`count`, `next`, `previous`, `results`) when returning lists.
- Custom actions require explicit verbs (e.g., `POST /api/jobs/{id}/accept-quote/`) and must still follow defensive patterns.
- Register drf-spectacular metadata for new endpoints and versions.

## Serialization Guidance

- Prefer `ModelSerializer` for CRUD endpoints; fall back to `Serializer` when orchestrating non-model payloads (e.g., command objects).
- Keep serializers thin: validations belong in `validate_*`/`validate` methods or the service layer, not in views.
- Use explicit nested serializers for related collections only when the API truly needs embedded data; otherwise return IDs and let clients hydrate separately.
- When nesting, mark child serializers as `many=True`, set `read_only=True` for display-only relations, and funnel write operations through dedicated endpoints or service calls.
- Strip legacy fields and expose versioned schemas using serializer context (see patterns in `.kilocode/rules/03-api-design-standards.md`).
- Enforce type hints on serializer methods, validate enums via `ChoiceField`, and map Decimal fields to `DecimalField(max_digits=..., decimal_places=...)`.

## Data Handling & Persistence

- Validate inputs early and run `Model.full_clean()` inside overridden `save()` methods.
- Wrap multi-step operations in `transaction.atomic()`; use savepoints when combining several risky operations and roll back on failure.
- Keep `CostSet.summary` and `ext_refs` updated; use `Decimal` for currency values and timezone-aware datetimes (UTC).
- Cache cautiously; invalidate caches immediately after writes (see patterns in `.kilocode/rules/04-data-handling-persistence.md`).

## Error Management & Logging

- Every `except` block must call `persist_app_error(...)` with context and re-raise (or handle according to documented business rules).
- Use structured logging (`extra={...}`) with operation names, identifiers, and status flags.
- Decorate long-running functions with performance logging (see `log_performance` decorator pattern) to capture execution time and query counts.

## Quality & Testing

- Automated tests are currently optional; prioritize functionality and thorough manual validation (follow the checklists in `.kilocode/rules/06-testing-quality-assurance.md`).
- Design code to be testable later: use dependency injection, small focused functions, deterministic logic, and avoid hidden globals.
- When you add tests, mirror the documented structure under each app’s `tests/` package and reuse factories/fixtures once available.

## Security & Performance

- Respect JWT configuration in `settings.py`: secure cookies, 8-hour access tokens, 1-day refresh tokens, blacklist after rotation.
- Optimize database work through custom managers/querysets using `select_related`, `prefetch_related`, and annotations to avoid N+1 and compute totals.
- Sanitize external inputs (especially Xero/webhooks); never trust client data or bypass backend validation.

## Good Practices Cheat Sheet

- Apply SOLID, Clean Code, and Object Calisthenics: single responsibility, early returns, shallow indentation.
- Prefer `match` (Python 3.10+) or dictionary dispatch over deep `if/elif` ladders.
- Use expressive names, remove dead code, and write comments sparingly to explain “why” rather than “what”.
- Wrap primitives in value objects or dataclasses when behavior or validation grows.

## Agent Workflow Checklist

- Review `.kilocode/rules/README.md` before starting significant changes.
- Validate inputs upfront, wrap risky operations in transactions, and persist all exceptions.
- For new features: design the service layer, ensure CostSet/CostLine usage, update API contracts, and document manual validation steps.
- After implementing changes: run relevant tox/prettier commands, perform documented manual checks, and summarize findings in PRs or handoffs.

Stay defensive, protect the CostSet/CostLine architecture, and keep the backend production-ready even without automated tests.
