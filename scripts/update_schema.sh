#!/bin/bash
# Regenerate the OpenAPI schema from the backend and rebuild the frontend API client.
# Run from the repo root.
set -e

cd "$(git rev-parse --show-toplevel)"
poetry run python manage.py spectacular --format openapi > frontend/schema.yml
cd frontend
npm run update-schema
