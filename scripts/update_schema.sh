#!/bin/bash
# Regenerate the OpenAPI schema from the backend and rebuild the frontend API client.
# Run from any directory.
set -e

cd "$(git rev-parse --show-toplevel)"
scripts/regen_openapi_schema.sh
cd frontend
npm run gen:api
