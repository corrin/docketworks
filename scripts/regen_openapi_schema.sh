#!/bin/bash
# Atomically regenerate frontend/schema.yml from drf-spectacular.
# Writes to a temp file, formats with prettier, and moves into place only when
# the content actually changes — so schema.yml is never empty mid-run and
# unchanged regenerations are a true no-op.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

tmp="frontend/.schema.yml.new"
target="frontend/schema.yml"

trap 'rm -f "$tmp"' EXIT

poetry run python manage.py spectacular --format openapi --file "$tmp"
(cd frontend && npx prettier --parser yaml --write "$(basename "$tmp")")

if ! cmp -s "$tmp" "$target"; then
    mv "$tmp" "$target"
fi
