# Codesight Setup Plan

## Context

Codesight is already installed (`npx codesight` works, v1.10.0) and has been run manually — there are three untracked `.codesight/` directories (root, `frontend/`, `docs/`). However nothing is committed, there's no config file, no `.codesightignore`, and it's not integrated into any automation. The CLAUDE.md already references codesight wiki articles and MCP tools, so it's actively being used — just not systematically maintained.

Goal: make codesight output always fresh, committed to the repo, and effortless.

---

## Current State

- **Root `.codesight/`** — full backend+frontend scan (61 models, 181 components, wiki articles)
- **`frontend/.codesight/`** — frontend-only scan (vue/ts focused)
- **`docs/.codesight/`** — knowledge mode scan (110 notes from markdown docs)
- **No config file** — defaults used everywhere
- **Not in git** — all three dirs are untracked
- **Not in `.gitignore`** — just never added
- **Pre-commit hooks** — extensive (black, isort, flake8, schema gen, etc.) via `.pre-commit-config.yaml`
- **Pre-push hook** — runs frontend unit tests, lint, type-check

---

## Decisions

### Run it in frontend separately? No.

The root scan already picks up the frontend (181 UI components appear in root output). Running a separate `frontend/.codesight/` duplicates work and creates two sources of truth. The root scan gives the full picture — backend models, frontend components, and the relationships between them.

**Exception:** The `docs/` knowledge scan (`--mode knowledge`) IS worth keeping separate because it serves a different purpose (mapping specs, meeting notes, decisions) and uses a different mode flag.

### Commit to git? Yes.

The output is deterministic (no LLM, ~200ms). Committing it means:
- Every developer and CI run gets the same context without running codesight first
- Git diff shows what changed structurally between commits
- AI assistants in any environment (not just local) can read the wiki

### When to regenerate? Pre-commit hook.

Not pre-push (too late — you want fresh context while developing). Not `--watch` (wasteful, runs on every save). A pre-commit hook is the right cadence: regenerate right before code is committed, so the committed `.codesight/` always matches the committed code.

### Wiki mode? Yes, always.

The wiki articles are what CLAUDE.md references for the two-step orient/verify workflow. Without `--wiki`, you only get `CODESIGHT.md` which is a single large file. The wiki gives targeted articles (~200-300 tokens each) that AI assistants can load selectively. Always run with `--wiki`.

---

## Implementation

### Step 1: Create `codesight.config.json`

```json
{
  "wiki": true
}
```

This makes `--wiki` the default so you can just run `npx codesight` without flags.

### Step 2: Create `.codesightignore`

Exclude things that add noise:

```
# Test fixtures and generated files
frontend/tests/fixtures/
frontend/schema.yml
frontend/src/api/generated/

# Build artifacts
frontend/dist/
frontend/node_modules/
node_modules/

# Docs codesight (separate knowledge scan)
docs/.codesight/
```

### Step 3: Add pre-commit hook to `.pre-commit-config.yaml`

Add two hooks at the end of the local hooks list:

```yaml
- id: codesight-code
  name: Regenerate codesight context map
  entry: bash -c 'npx codesight --wiki && git add .codesight/'
  language: system
  pass_filenames: false
  always_run: true

- id: codesight-knowledge
  name: Regenerate codesight knowledge map
  entry: bash -c 'npx codesight --mode knowledge -o docs/.codesight && git add docs/.codesight/'
  language: system
  pass_filenames: false
  always_run: true
```

### Step 4: Remove `frontend/.codesight/`

Delete the separate frontend scan — the root scan covers it. The frontend CLAUDE.md can reference the root `.codesight/wiki/` articles.

### Step 5: Commit the `.codesight/` and `docs/.codesight/` directories

Add both to git so they're tracked going forward.

### Step 6: Add to `.gitignore` — the frontend copy only

```
frontend/.codesight/
```

This prevents the redundant frontend-only scan from being accidentally committed.

---

## Verification

1. Run `npx codesight --wiki` — confirm `.codesight/` regenerates with wiki articles
2. Run `npx codesight --mode knowledge -o docs/.codesight` — confirm docs knowledge map regenerates
3. Make a trivial change, run `git commit` — confirm pre-commit hooks regenerate codesight and stage the output
4. Verify `frontend/.codesight/` is gone and `.gitignore` excludes it
5. Confirm CLAUDE.md references still work (wiki index, overview, domain articles all exist)

---

## Files to modify

- `codesight.config.json` (new) — wiki default
- `.codesightignore` (new) — noise exclusions
- `.pre-commit-config.yaml` — add two hooks
- `.gitignore` — add `frontend/.codesight/`
- Delete `frontend/.codesight/` directory
