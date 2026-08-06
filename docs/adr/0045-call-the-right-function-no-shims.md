# 0045 — Call the right function; never return a shape the caller must decode

A function returns one shape. When a caller must run `isinstance`, `hasattr` or `type()` to discover what it was handed, the seam is wrong — fix the seam, not the caller.

## Rules

Runtime type inspection belongs only at a boundary where the input genuinely arrives untyped: an AST, parsed YAML or JSON, a webhook body. There the shape is discovered and converted into a typed one immediately, and the inspection never travels further into the code. Anywhere else you already know the type, because you wrote the function that produced it.

Never author a union and then discriminate it. `tuple[Job, Staff] | str` passes mypy and reads as economical, but it obliges every call site to ask which arm it received, and every future call site to remember. The checker being satisfied is not the test; the test is whether a caller can use the result without first classifying it.

When two callers need the same setup but different behaviour, parameterise the behaviour rather than returning a decodable result. Two assignment functions sharing a ten-line lookup became one `_change_job_assignment(..., *, attach: bool)`; the first attempt instead returned "the rows, or the error message" and made both callers unpack it with `isinstance`.

When absence is an ordinary answer rather than a fault, ask a question that can answer it: `Model.objects.filter(...).first()` and a guard clause, not `get()` wrapped in a handler that rebuilds the same information the query already had. An exception handler is for an exception, and a row that is legitimately missing is not one.

**Returning `X | None` is the same defect one step earlier, and is the one to resist hardest.** A function that can return `None` has not solved a problem; it has moved the problem to every caller, and there are always more callers than functions. Each one must decide what `None` means, they will not all decide the same thing, and the checker enforces only that they decide *something*. Before writing `-> X | None`, take one of these instead: raise, when absence means a caller asked for something that should exist; return the neutral value, when one exists and every caller would construct it anyway (`""`, `[]`, `Decimal("0")`); or move the question to the call site, which already knows what it would do about the answer. Reserve `X | None` for absence that is a real business state with a real branch — and then say so in the name, so a reader learns it from the call rather than the signature.

`dict.get(key, fallback)` and `getattr(obj, name, default)` on our own shapes are the same defect wearing different clothes — they answer a question the contract should already have settled. Validate at the edge, then subscript and attribute-access directly.

## Do not

- **Reach for `isinstance` to make a union usable** — the union is the bug; the check is the symptom. Deleting the union deletes both.
- **Add an "and it might also return X" arm to an existing function** — that converts every existing caller into a decoder without touching them, and the checker will not tell you which ones now handle a case they never handled before.
