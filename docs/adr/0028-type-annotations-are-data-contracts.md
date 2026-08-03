# 0028 — Type annotations are data contracts

Annotations describe the shapes the application depends on; they are not checker-silencing syntax.

## Rules

- Never add `Any`, containers of `Any`, broad `object`, fake `| None`, broad unions, casts, or ignores to make mypy pass. A helper typed `str | None` that actually requires a real name has just told every future caller that `None` is supported — the annotation has encoded malformed data as valid.
- `Any`/`object` are allowed only at genuinely external or dynamic boundaries, and must be validated or converted into a typed shape immediately. `T | None` only when `None` is a real business value with a real handler.
- A type complex enough to hide domain meaning gets a name: dataclass for internal domain values, `TypedDict` for dict-shaped payloads, `Protocol` for behaviour, alias for readable composition. `OrdersByCustomer = dict[str, list[Order]]`, not `dict[str, list[tuple[str, int, float]]]` that readers must decode positionally.
- Validate, then access directly: `payload["job_id"]` after schema validation, not `payload.get("job_id", "")`. `dict.get()` fallbacks and `hasattr()` probes outside dynamic boundaries mean the contract is unclear — fix the contract. Missing required value → raise first (`if not x: raise …`), never nest the happy path under `if value:`.
- Tests hold the same bar: a test that casts an application function to `Any` stops checking the exact contract it exists to protect.
