# 0032 — Less code is better: prefer libraries over homegrown implementations

For any capability a well-maintained library provides, install the library; writing our own is a recorded exception.

## Rules

- Reach for a maintained library first. "We added a dependency" is the default; "we wrote our own" carries the burden of proof — a stated line in the PR description, or an ADR for a significant or repeated surface. The code we own is code we test, secure, and carry forever; unwritten code has no bugs.
- The reasons that justify custom code: no library covers the need (or the closest are unmaintained / license-incompatible); the need is so small that a dependency's supply-chain and transitive cost outweighs the lines saved; the library would demand more glue than it removes.
- Replacing owned code with a library, or deleting owned code a library makes redundant, needs no justification — done atomically with every call site migrated in the same PR (ADR 0017). ADR 0031 (homegrown `debugLog` → the `debug` library) is the pattern.
- Dependencies are still weighed (maintenance, license, transitive cost). This raises the bar for writing code; it does not remove the bar for adding dependencies.
