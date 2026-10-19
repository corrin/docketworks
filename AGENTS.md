Read and follow [CLAUDE.md](CLAUDE.md) before making any change in this repository.

## Cursor Cloud specific instructions

The Cloud Agent environment starts PostgreSQL, Redis, Django on port 8000, Celery worker and beat, and the compiled frontend on port 4173. Open the app at http://localhost:4173. A local office login, `dev@docketworks.local`, is created on first boot; the password is in `/home/ubuntu/docketworks-data/dev-login`. Xero sync is off on that database, and a local customer named Harbour Fabrication is there so a job can be created without a Xero app. Do not `source .env`. Unit tests are `uv run pytest`. In `frontend/`, `npm run type-check` and `npm run test:unit` are the frontend checks.
