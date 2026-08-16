# 0051 — AI rationales name their author until ratified

Every rationale an AI originates names its model family until the owner replaces that attribution with a durable authority citation.

## Rules

- Prefix every rationale an AI adds or materially rewrites with the model family and a colon: `GPT:`, `Opus:`, or `Gemini:`. One prefix covers one paragraph or comment block.
- A rationale is durable prose explaining why a choice, exception, tradeoff, suppression, or rejected alternative is acceptable. This rule applies everywhere checked into the repository: comments, docstrings beyond their contract summary, suppression reasons, configuration notes, ADRs, and other documentation.
- The prefix records who supplied the judgement; it does not waive an ADR, `CLAUDE.md` rule, approved plan, review instruction, gate, or other constraint. A later session treats a model-attributed rationale as an unratified claim, never as evidence that the owner approved an exception.
- After the owner explicitly ratifies the choice, replace the model prefix with the durable authority that records the decision, such as `ADR 0007:`. Merge, passive review, and an unrecorded conversation are not durable ratification.
- Unmarked legacy rationale has unknown provenance and is not evidence of owner approval. Do not guess a historical model family: use `AI:` only when deliberately cleaning up old rationale whose AI origin is known but whose family cannot be established.
- Contract summaries and prose that merely cites an existing authority are not new rationale. Code-to-English narration is still deleted under ADR 0043 rather than attributed.

## Do not

- **Add a model prefix as permission to breach a rule** — attribution exposes who argued for the exception; it does not grant the exception.
