# Watch `.git/logs/HEAD` in Django autoreload so `BUILD_ID` stays fresh

## Context

E2E tests on `feat/jobevent-audit` enter an infinite redirect loop on `/login`, timing out at `frontend/tests/fixtures/auth.ts:30` waiting for `#username`.

Root cause: `settings.BUILD_ID` is captured at settings-import time (`docketworks/settings.py:20`, `subprocess.run(["git", "rev-parse", "HEAD"], ...)`). Django runserver's autoreloader only restarts on Python file mtime changes. So a `git commit` that advances `HEAD` without leaving any further Python edits on disk leaves the backend reporting the pre-commit SHA. The frontend's vite dev server reads `HEAD` per request inside `transformIndexHtml.handler` (`frontend/vite.config.ts:49`), so the meta tag reflects current `HEAD`. Mismatch → `frontend/src/composables/useVersionCheck.ts:16` redirects to `/login?__v=<backend-sha>` → reload → same mismatch → infinite loop.

Concrete sequence this session: an edit to `apps/job/services/job_rest_service.py` triggered autoreload, which captured `BUILD_ID = a6813a4e…`. The subsequent `git commit` (`3727fd46…`) changed no file on disk, so runserver never reloaded; the backend kept reporting `a6813a4e` while the frontend and disk moved to `3727fd46`.

## Approach

Register `.git/logs/HEAD` as an extra watched file for Django's autoreloader. Git appends to this file on every `HEAD`-moving operation — commit, checkout, reset, merge, rebase, cherry-pick — which is exactly the event set we need. Watching `.git/HEAD` alone is insufficient: that file only changes on branch switches, not on commits to the current branch.

Plumbed via the `django.utils.autoreload.autoreload_started` signal in `apps/workflow/apps.py:WorkflowConfig.ready()`. The signal only fires under runserver, so gunicorn/prod behavior is unchanged — the existing "captured at import time, gunicorn restart on deploy picks up the new SHA" semantic is preserved.

No API contract change, no conditional in the view, no subprocess-per-request, no dev/prod fork.

## Files to modify

- **`apps/workflow/apps.py`** — add module-level signal handler `_watch_git_head` and connect it inside `WorkflowConfig.ready()`:

  ```python
  from django.utils.autoreload import autoreload_started

  def _watch_git_head(sender, **kwargs) -> None:
      git_log = settings.BASE_DIR / ".git" / "logs" / "HEAD"
      if git_log.exists():
          sender.watch_file(git_log)
  ```

  And in `ready()` (after the existing calls):

  ```python
  autoreload_started.connect(_watch_git_head)
  ```

  The `.exists()` guard is cheap insurance for environments without a git checkout (e.g. if a container image were ever built without `.git/`); it matches the defensive style of `BUILD_ID`'s subprocess call failing fast if `.git/` is absent — here we silently no-op instead of crashing, because watching-a-nonexistent-file would crash runserver even in valid no-git environments.

## Verification

1. Start runserver. `curl /api/build-id/` → note SHA matches `git rev-parse HEAD`.
2. `git commit --allow-empty -m probe`. Runserver log shows a reload. `curl /api/build-id/` → new SHA.
3. `git checkout -b probe-branch && git checkout -` (or similar no-op branch dance). Runserver reloads on each checkout; `/api/build-id/` reflects the ref `HEAD` points to.
4. Re-run `npm run test:e2e` from `frontend/`. The login fixture should no longer hit a `__v=` redirect loop. (Verifying the whole suite is out of scope for this change — we're only confirming the redirect loop is resolved.)

## Non-goals

- Prod is untouched. Gunicorn doesn't use the autoreloader; `autoreload_started` never fires there. `BUILD_ID` continues to be captured at settings-import time, and `deploy.sh`'s gunicorn restart continues to advance it.
- Not adding an E2E pre-flight SHA-drift check. The underlying desync is what's being fixed; a pre-flight check would be a belt-and-braces addition that can be considered later if this proves insufficient.
- Not changing `BuildIdAPIView` or `useVersionCheck.ts`.
