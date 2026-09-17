# Release process

Carried forward from v1's practice (ADR 0029 owns the branch topology; the
notes convention below was previously unwritten — this file makes it
durable).

## Branches and promotion

- Feature PRs merge to `main`. UAT instances track `origin/main`, so merged
  work reaches UAT on the next deploy (the Deploy-to-UAT workflow updates
  the box's repo mirror on every push to `main`; an operator runs
  `scripts/server/deploy.sh` to release it to the UAT instance).
- **A release PR promotes `main` to `production`** after UAT verification:
  `sudo scripts/server/verify-instance.sh <client> uat --e2e` green on the deployed UAT
  instance (ADR 0064). Production instances track `origin/production`.
- **PVT is the same command on production**, `verify-instance.sh <client> prod --e2e
  --production`, after the deploy. It runs the suite on a copy of the database with the fake
  Xero and fences users out for the run (about 35 minutes), so
  it is a declared window; uptime monitors will alert. Neither run is merge evidence: the
  gate before merge is `./scripts/ops/run_e2e.sh` on a workstation against real Xero.
- **A two-browser live-update smoke follows PVT.** Sign in to the kanban board in two
  browsers, move a card in one, and confirm it appears in the other without a reload. That
  exercises the whole push path (signal, commit hook, Redis fan-out, stream, client
  reconcile) in one action, and it is the only check that fails visibly when the Redis
  pub/sub listener is dead while streams stay connected; no E2E spec covers it.
- Hotfixes merge into `production` and are back-merged to `main`.
- **Release PRs and hotfix back-merges are merged with a merge commit — never
  squashed, never rebased.** Squash is right for a feature PR, where one
  reviewable change lands on `main`; it is wrong for a promotion, because the
  squash commit records no parent on the source branch. The two branches then
  hold identical trees while their merge base stays frozen at the last honest
  merge, and the next release PR diffs from there and re-proposes every commit
  since. Check the merge-method dropdown before merging either one.
- After promotion `production` is an ancestor of `main`, so
  `git merge-base --is-ancestor origin/production origin/main` succeeds. If it
  fails, a promotion was squashed: repair it by merging `origin/production`
  into `main` (the trees already agree, so the merge changes no file) rather
  than by force-pushing `production`, which the prod hosts track and the
  `prod-*` tags name.

## Before the deploy

- **Every required environment variable reaches each instance's `.env` first.**
  `deploy.sh` now checks the target release's settings against the instance `.env`
  before it stops any unit, so a missing variable fails the deploy with the instance
  still up; it does not add the variable. New ones arrive with their feature
  (`SESSION_REPLAY_STORAGE_ROOT` with session replay, `XERO_FAKE=false` with ADR 0060).
- **A data migration that can refuse is rehearsed against a production restore.** When the
  checkout is ahead of the archive, re-insert this installation's private rows after
  `migrate`, not after `pg_restore`: the archive's tables predate columns the checkout
  has removed, and a positional copy into the older shape fails at the first row. A data
  migration that refuses runs with the units stopped, so rehearse it against a restore
  first.
- **The integration tier is the merge gate for anything that touches Xero, the AI
  gateway, Maps, the phone provider or mail** (ADR 0050). It is human-run because CI
  has no sandbox credentials: `./scripts/ops/run_integration_tests.sh` before the
  release PR merges, and the PR states any change to the number of vendor calls a user
  action or a test run makes.

## Every genuine production deploy gets a GitHub Release

Tag scheme: `prod-YYYY-MM-DD-<sha8>` (the date and the short SHA of the
promoted commit), title `Production release <tag>`, created when the
release PR merges — before or alongside the server-side
`sudo scripts/server/deploy.sh <client>-prod`:

```bash
sha8=$(git rev-parse --short=8 origin/production)
tag="prod-$(date +%Y-%m-%d)-$sha8"
gh release create "$tag" --target production --title "Production release $tag" --notes-file <notes>
```

The release is the durable record of what production ran and when;
`deploy-state.env` on each host records what that instance currently runs.

## Release notes are written for the people who use the app

The audience is the front desk and the workshop, not developers. v1's
`prod-2026-08-02-ae5257d6` release is the exemplar. Structure:

1. **Opening line:** `Compared with previous production release <tag>.`
2. **One section per feature**, named by what the user sees (bold the UI
   names). Describe what the screen does for the person using it and what
   changed about their day — never commit prose, file names, or internals.
3. **Other Changes** — a short list of the smaller user-visible changes.
4. **Where Problems Are Most Likely** — the honest watch-list: which
   screens this release reworked under the hood, what "wrong" would look
   like there, and what to do about it. Each item tells the reader what to
   check and to **report with the job/error id rather than working around
   it**. This section is the release's real safety net and is never
   omitted or padded.
5. **Closing line:** `Please report anything that looks wrong rather than
   working around it.`

What to leave out: refactors, dependency bumps, test changes, anything with
no user-observable behaviour — unless it belongs in Where Problems Are Most
Likely because it could break something user-visible.

Source material: the merged PRs between the previous `prod-*` tag and the
new one (`git log <prev-tag>..production --merges`), read for user-visible
behaviour, not summarised mechanically.
