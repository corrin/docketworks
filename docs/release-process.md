# Release process

Carried forward from v1's practice (ADR 0029 owns the branch topology; the
notes convention below was previously unwritten — this file makes it
durable).

## Branches and promotion

- Feature PRs merge to `main`. UAT instances track `origin/main`, so merged
  work reaches UAT on the next deploy (the Deploy-to-UAT workflow updates
  the box's repo mirror on every push to `main`; an operator runs
  `scripts/server/deploy.sh` to release it to the UAT instance).
- **A release PR promotes `main` to `production`** after UAT verification.
  Production instances track `origin/production`.
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
