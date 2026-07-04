# 0028 — Type annotations are data contracts

Mypy annotations describe the valid shapes this application depends on; they are not a checker-silencing syntax.

## Problem

The app relies on strict data contracts to stay bug-free. A type shortcut can weaken those contracts as badly as a runtime fallback: `Any` opts out of the model entirely, and `T | None` declares that missing data is a valid business value. When mypy is enforced through a baseline, the temptation is to make touched code pass by widening types rather than making the touched boundary correct.

## Decision

When touching Python code, improve its mypy state by preserving or tightening the real contract. Do not add `Any`, broad `object`, fake optionality, broad unions, casts, or ignores to avoid local typing work. `Any` and `object` are allowed only at unavoidable external or dynamic boundaries, and must be immediately validated or converted into a typed shape. `T | None` is allowed only when `None` is genuinely valid and intentionally handled. If a type becomes complex enough to hide domain meaning, introduce a named type: dataclass for internal domain values, `TypedDict` for dict-shaped payloads, protocol for behaviour, or a simple alias for readable composition.

Contract discipline applies to control flow as well as annotations. Fallback-style `dict.get()`, `hasattr()` probes, and happy-case-first branching are not banned, but they are smells in application code because they often mean the contract is unclear. Use them at genuine dynamic boundaries only, then validate or convert into a named shape. Once code indexes, mutates, or reads attributes from a value, give that value a real type. For required data, prefer direct access after validation so malformed input fails loudly instead of becoming a default.

## Why

Types are executable documentation for the data model. A helper typed as accepting `str | None` tells every future caller that `None` is supported; if the helper actually needs a real supplier name, that annotation has encoded malformed data as valid data. A test that casts an application function to `Any` stops checking the exact contract the test should protect. Keeping touched code strict means the mypy baseline can shrink without turning historical debt into new ambiguity.

Readable named types also make review possible. `dict[str, list[tuple[str, list[tuple[str, int, float]]]]]` forces readers to decode positional meaning. `OrdersByCustomer = dict[str, list[Order]]`, with `Order` and `OrderLine` named, states the model directly and gives mypy stable structure to enforce.

Small code-shape choices carry the same signal. Use `payload["job_id"]` after serializer or schema validation instead of `payload.get("job_id", "")`. Introduce `JobPayload` as a `TypedDict` instead of passing `dict[str, object]` once callers read keys from it. Load the required annotation or relation before rendering instead of probing with `hasattr()`. Check `if missing_required_value: raise ...` before the main path instead of nesting the whole function under `if value:`.

## Alternatives considered

- **Use broad types to minimise PR size.** Defendable when type checking is advisory and delivery speed matters more than local precision. Rejected here: this codebase uses mypy as a contract ratchet, and broad types let bad data travel further.
- **Treat all historical untyped code as immediately in scope.** Defendable for a dedicated type-hardening project. Rejected for normal work: the baseline records existing debt; each PR fixes the code it touches rather than boiling the ocean.
- **Allow casts and ignores wherever mypy cannot infer intent.** Defendable in dynamic-heavy Python code. Rejected for application logic: casts and ignores must be narrow, justified, and adjacent to an external/dynamic boundary, not a shortcut around our own model.

## Consequences

Touched functions and call boundaries often need a little more local cleanup than the original change suggests. The payoff is that annotations stay truthful, the baseline only shrinks, and future readers can trust a type signature as the application contract. Complex payloads require named structures instead of dense inline annotations.
