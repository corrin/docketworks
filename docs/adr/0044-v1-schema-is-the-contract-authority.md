# 0044 — v1's frozen schema is the contract authority, and a ratchet enforces it

For every operation both schemas expose, v2's declaration may not be weaker than v1's — v1's `frontend/schema.yml` is the authority because DRF derived it from the models, and `scripts/schema_parity_diff.py` fails the build when v2 drifts weaker.

## Rules

v1's schema is a *derived* artefact: every serializer in it descends from `ModelSerializer` (68 of them at fork commit `2594e93f`, which is what `frontend/schema.yml` was frozen from), so `format: uuid`, nullability and required-ness in it came from the model fields rather than from anyone's typing. v2 hand-writes all 278 ninja `Schema` classes and derives nothing, which is why 176 properties ended up declared more weakly than v1 with no drift entry anywhere — nobody chose a weaker type; nothing was watching.

Treat `frontend/schema.yml` as read-only. It is v1's frozen 306-operation baseline and the left-hand side of every parity comparison; the exported v2 schema is a separate file, `frontend/schema.v2.yml`.

When you add or port an operation, run `uv run python -m scripts.schema_parity_diff`. It fails on any property where v2 is weaker than v1 in one of three ways: a lost `format: uuid`, a value v1 guarantees that v2 admits null for, or a property v1 requires that v2 makes optional. The known set lives in `scripts/schema-contract-gaps.txt` and the live set must **equal** it. A new gap fails, and a recorded gap that no longer exists also fails — otherwise the file rots into a wishlist that only ever grows.

The nullable check applies to request and response bodies only, never to parameters, because a URL cannot carry null — a query string transmits text or nothing, so "absent" is the only no-value a parameter has and `anyOf: [{...}, {type: null}]` is just how ninja spells a `| None = None` default. That suppresses 34 parameter differences, of which `required` reports only one; the other 33 are optional in both schemas and are suppressed because they are not defects, not because something else covers them. Two practical consequences: widening a *parameter* annotation to `| None` is invisible to this gate, and a parameter v1 declares required-and-non-nullable that v2 declares required-but-nullable is caught by neither check (zero instances today).

Fix a gap at the backend declaration, never by post-processing generated output. The frontend's typed client is generated from the exported schema, so a fix made downstream is a fix the next regeneration discards.

When a gap is a genuine behavioural divergence rather than a mistake — the producing service really can return `None` — record the reason in `docs/accepted-api-differences.yml` and leave the entry in `schema-contract-gaps.txt`. The gate compares property paths and never reads the ledger, so removing an explained entry fails as a new regression. Explaining a gap documents it; only fixing it removes it.

`scripts/export_openapi.py` and `scripts/schema_parity_diff.py` must read the same Django settings module (`config.settings_test`). Different modules could describe different API surfaces, leaving the parity diff guarding a schema the frontend never generates from.

Prefer `ModelSchema` when a wire shape *is* a model's shape, so the derivation happens in code rather than in someone's attention. Nothing enforces this and v2 currently uses it zero times; it is a direction for new code, not a claim about the tree. Most schemas are genuinely not model-shaped — reports, aggregates and requests spanning several models — and hand-writing those is correct. The ratchet is what protects them.

## Do not

- **Converting the 278 schemas wholesale to `ModelSchema`** — only 27 of them share a name with a model after stripping the usual `Out`/`Request`/`Data` suffixes. The rest would have to be bent into a model shape they do not have.
- **Widening a body or response annotation to make the checker pass** — a `| None` added to silence mypy becomes a contract promise that null can arrive, and the ratchet records it as a regression. Fix the producer instead. (On a parameter the ratchet will not catch you, which is a reason for more care there, not less.)
- **Regenerating the gaps file to make a failure go away** — `--update-baseline` is for recording a fix, not for absorbing one. The file may only shrink.
