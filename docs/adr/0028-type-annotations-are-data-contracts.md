# 0028 — Type annotations are data contracts

Annotations describe the shapes the application depends on; they are not checker-silencing syntax.

## Rules

- Never add `Any`, containers of `Any`, broad `object`, fake `| None`, broad unions, casts, or ignores to make mypy pass. A helper typed `str | None` that actually requires a real name has just told every future caller that `None` is supported — the annotation has encoded malformed data as valid.
- `Any`/`object` are allowed only at genuinely external or dynamic boundaries, and must be validated or converted into a typed shape immediately. The same condition governs casts and ignores: narrow, justified, and adjacent to that boundary — never a shortcut around our own model. `T | None` only when `None` is a real business value with a real handler.
- A type complex enough to hide domain meaning gets a name: dataclass for internal domain values, `TypedDict` for dict-shaped payloads, `Protocol` for behaviour, alias for readable composition. `OrdersByCustomer = dict[str, list[Order]]`, not `dict[str, list[tuple[str, int, float]]]` that readers must decode positionally.
- Validate, then access directly: `payload["job_id"]` after schema validation, not `payload.get("job_id", "")`. `dict.get()` fallbacks and `hasattr()` probes outside dynamic boundaries mean the contract is unclear — fix the contract. Missing required value → raise first (`if not x: raise …`), never nest the happy path under `if value:`.
- Tests hold the same bar: a test that casts an application function to `Any` stops checking the exact contract it exists to protect.
- When the checker rejects a line you just wrote, suspect your own scaffolding before the code: the first candidate fix is deleting the annotation, guard, or requirement you invented a moment ago — not appending narrowing code. A `set[str]` annotation whose only use was a membership test (which works on `set[str | None]`) demanded a dead `is not None` filter plus a comment defending the filter; removing the annotation deleted all three.

## Do not

- **Appease the checker with layered workarounds** — a narrowing comprehension, a defensive branch for an impossible case, and a comment explaining why the impossible is handled are three artefacts defending one wrong annotation. Each layer reads reasonable on its own; that is how entropy passes review one line at a time.
