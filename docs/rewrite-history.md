# Rewrite history — what was decided, found and measured

The rewrite's own record: rulings and their dates, findings whose value is the
record rather than a rule, and measurements with no other owner. Read it when
asking *why is it like this?*

**This file exists so [`rewrite-status.md`](rewrite-status.md) can only shrink.**
Status is the task list and nothing else; anything worth saying that is not a
task belongs here, so explaining a decision never grows the file a session reads
to find its next job. Neither is deleted now that the cutover has happened: the
port has a tail, and the reasoning behind a decision outlives the release that
carried it.

**It is not a second copy of the ADRs, and keeping that boundary is what stops
it becoming a third backlog.** A fact that constrains code lives in an ADR or a
seam comment at the code it constrains; this file links there rather than
restating it. Nothing here is a task.

## Cutover

**2026-08-14: the 15 August window was declined and cutover moved one week to
22–23 August.** At decision time MUST-tier specs were still red — among them
`/timesheets/weekly` (declared MUST that same day, unstarted),
`workshop-my-time-view`, `staff/create-staff`, `company-defaults`, the CRM
people pair, `pickup-address` and the unconfirmed `supplier-alias-search` — and
the rehearsal items were open, so the functionality gate could not pass inside
the window. Scope was frozen as tiered that day; deferral moves the date, never
the definition of done.

**2026-08-14 tiering.** Reports slip about a week past cutover. Process
documents stay deferred except the four safety-AI operations.
`/purchasing/mappings` slips about a week — the purchasing MUST is the ability
to make purchase orders, which the green purchasing specs plus `pickup-address`
cover. Price-list extraction is its own deferred slice. Schedule slips by more
than a week: no scheduling algorithm exists in either repo's backend, so the
slice is algorithm plus page plus fresh spec. The admin tail is SHOULD-plus —
really painful to slip — and AI is SHOULD rather than MUST.

**Every deferred screen ships spec-first (2026-08-14).** Most have no v1 spec to
port, so the slice authors one and is done when it is green. The spec is written
with the slice, not before cutover — an explicit choice not to spend pre-flip
hours on specs for unbuilt screens.

## Rulings that closed a question

**Password tokens are fingerprint-bound with no grandfathering; the deploy
carrying it logs every session out once (2026-08-31).** Every JWT now carries
a fingerprint of the password hash (`apps/core/auth.py`), so a change or
reset evicts every other session. Tokens minted before the claim existed fail
the same comparison — owner accepted the one-time fleet-wide re-login
(overnight deploys make it a non-event) over a 90-day window in which a
pre-deploy token would outlive the password it was issued against (ADR 0017:
no transitional code).

**v1's `pages/purchasing/pricing.vue` is not the pricing-upload feature; the
file is not ported (2026-08-14).** The page as deployed — verified on v1's
`origin/production` — accepts a dropped file and discards it: the handler is a
`debug` log line, it makes zero API calls, and `git log --all -S` finds no
frontend caller of the extraction endpoint in any branch of v1's history. The
capability itself is committed deferred work.

**`parser_version` is the re-parse marker, and an operator's hand-validation
outranks the parser** — never overwrite a validated mapping. Settled; do not
re-litigate.

**v1's `format_period_label` was dead code with zero call sites** and was not
ported.

**Four E2E specs claimed a live Xero tenant and do not touch one**
(`sales-forecast`, `payroll-reconciliation`, `create-timesheet-entry`,
`job-cost-entry-data`); they read restore-populated mirror tables only.

**Lists scroll to load, they do not page or truncate (2026-08-22).** The
people directory and companies report fetch the server's default page and
append the next one when the foot of the list scrolls into view
(`LoadMoreSentinel`, with a visible Load more button as the keyboard path);
whenever the list has rows the running count is shown, and loading stops at
the last page. This supersedes the first-page-plus-search ruling of `143a56a`,
which hid the tail of a 1,000-row directory behind the search box. Full-height virtual
scrolling (scrollbar spanning every row, random-access page fetches) was
considered and declined on cutover weekend as roughly double the work; offset
paging stays on the backend because keyset paging is the feed answer, not a
sorted directory's.

**The company-defaults PATCH stays last-write-wins; no If-Match (2026-08-22).**
Rejected because the dirty-fields-only payload (`exclude_unset`) bounds any
conflict to two editors touching the same field, and ADR 0003's optimistic-
concurrency scope is Job/PO, not this singleton — a rarely-edited row does not
earn the extra mechanism.

**The job History tab offers Add Event, Undo and Linked Phone Calls to office
staff only (2026-08-23).** All three endpoints behind them —
`job_rest_jobs_events_create`, `job_jobs_undo_change_create` and
`crm_phone_calls_list` — require office staff, so a workshop user offered any
of those controls could only be refused by the server. v1 drew all three for
everyone and let the request 403.

**A `costline_updated` timeline entry renders as "Costline Updated"
(2026-08-23).** `timelineKind` maps the three entry types the tab draws and
throws on a fourth. v1 treated every entry that was not `costline_created` as
a job event, which is how a cost-line update came to render as a blue
"General" job event nobody could account for. An entry type the tab has no
rendering for is a fault to surface, not a shape to guess at.

**v1's `PhoneNumberManager` card is not ported (2026-08-23).** Contact methods
have one home in v2 — PersonDetailPage and CompanyDetailPage — and the calls
page's Assign Number panel covers the call-to-number flow the card existed for.

**Two phone-call automation ids changed from v1 (2026-08-23).** The linked-job
badge is per row — `PhoneCallTable-linked-job-{callId}`, not v1's shared
`PhoneCallTable-linked-job`, whose single id matched whichever linked row
sorted first, so an assertion on it could pass on a call the test never
touched. And `PhoneCallTable-job-select`, v1's native `<select>` of jobs, is
retired: the job is chosen through the shared `JobPicker`, which opens from
`PhoneCallTable-job-trigger` and lists `PhoneCallTable-job-option-{job_number}`.
`PhoneCallTable-job-search` is the same id it was in v1; only its owner
changed, from a hand-rolled filter box to the picker.

**A seeded phone call is recognised by its `[TEST]` description (2026-08-23).**
The phone provider is a pull-only portal, so an E2E environment can only
fabricate a call; `e2e_seed_phone_call` writes the `[TEST]` prefix into the
call's description, provider call id and account code, and `e2e_cleanup`
selects calls by `description__startswith`. Both of `PhoneCallRecord`'s
foreign keys are SET_NULL, so a call the cleanup cannot name outlives its job
and company as an orphan in the Unmatched queue with its recording file
stranded under `PHONE_RECORDING_STORAGE_ROOT`.

## Cross-report divergences, ported faithfully (2026-08-04)

v1's reports disagree with each other on definitions users can see side by side.
Each was ported as-is, because silently unifying them would be a functional
change. Unifying any of them is a user decision that has not been asked for.

- **Working days**: the KPI calendar counts public holidays as working days
  (`kpi_service.py`); the sales pipeline excludes them
  (`sales_pipeline_service.py::_working_days_between`). Both feed
  "per-working-day" numbers shown to the same user.
- **Valid invoices**: WIP counts DRAFT invoices at `total_excl_tax`
  (`wip_service.py`); the sales forecast excludes DRAFT and uses
  `total_incl_tax` (`sales_forecast_service.py`); `invoice_calculation`
  derives all-but-VOIDED/DELETED from the enum.
- **Quote transitions**: job-movement counts EVENTS, so a job re-entering
  `awaiting_approval` counts twice; the sales pipeline counts each JOB once.
  Both now take their window from
  `apps/accounting/services/report_windows.py`, so only the counting rule
  still differs.
- **Team billable %**: staff-performance uses the unweighted mean of per-staff
  percentages, and includes shop revenue in `total_revenue` while excluding
  shop hours from `billable_hours`; the timesheet screens use weighted
  total-over-total. Same person, different utilisation number.
- **Payroll hours source**: `payroll_reconciliation_service` reads
  `XeroPaySlip.timesheet_hours + leave_hours`; v1's `xero_hours.py` twin parses
  `raw_json` and hardcodes its window.

## Measurements

**Google returns no NZ region from Address Validation, 2026-09-02.** Measured
against six real addresses across four regions: `v1:validateAddress` returns no
`administrative_area_level_1` component for any New Zealand address, so the
`administrative_area_level_1 -> state` entry in `geocoding_service`'s
`_COMPONENT_FIELDS` has never fired here. That is why 513 of 522
`SupplierPickupAddress` rows have a NULL `state`, and why the few non-NULL ones
are v1 data-entry residue (`'Address changed 16/01/2012'`, `'1151'`,
`'Madeupville'`). The shop's own address therefore goes through **Places (New)**,
which does return it, and which takes the key in a header — the classic
Geocoding API also carries the region but is GET-only with the key in the query
string, which the credential-in-URL fable on `geocode_address` rules out.

Two shapes worth keeping: Google names most regions `"<Name> Region"` but
Auckland plainly `"Auckland"`, so the mapping strips an optional suffix before
looking the name up in the `holidays` package's own alias table rather than
maintaining a second copy. And **South Canterbury cannot be derived** — Google
answers `"Canterbury Region"` for Timaru exactly as for Christchurch, while
`holidays` carries South Canterbury as its own subdivision with its own
anniversary day, so such a business needs its subdivision set by hand.

The lesson generalised: the repo's hand-written Address Validation mock had no
`administrative_area_level_1` in it, and was right by accident. A mock authored
from documentation asserts what we hoped an API does. Capture a real response
first.

**Data scan, 2026-08-04.** Of 63 rows flagged as invalid, 32 were the model's
own contract being stricter than its column, and one "junk" blank purchase-order
line held $119.50 of received stock. Two rules came out of it, and they are the
reason this is recorded: when validation rejects long-standing production data,
suspect the model first; and test any destructive predicate against real data
before running it.

**Measure the database the claim is about.** The quoting/0002 "harmless"
misclassification came from measuring an already-normalised database rather than
a restore built the way cutover builds one.

**Sitemap shard, 2026-08-01.** The scraper reads `sitemap_0.xml` only, inherited
from v1. Measured 3,677 distinct product URLs against a 50,000-per-shard limit —
ample headroom, so this is a monitoring concern rather than a live bug. If the
catalogue ever spans a second shard those products become invisible AND get
retired by the discontinue sweep; the defence is `MIN_SITEMAP_COVERAGE`, which
refuses the sweep and persists an AppError when the sitemap lists under half the
live catalogue.

**v1 PR #522 deployed 2026-08-07.** Every dump taken before that date lacks the
31 repaired rows.

**Payroll integration suite first completed 2026-08-21.** All three tests green
against the live demo tenant inside one day's quota, `test_complete_weekly_payroll_lifecycle`
included — the posting path's first assertion against the real system. The run
earned its keep immediately: it caught the leave-request projection pricing
UNPAID leave at the full wage (a phantom $40 mismatch on any week containing an
unpaid day, fixed in the same session by deriving the multiplier from
`LeaveType.is_paid`), and the full E2E gate that followed (108 specs) caught
the weekly page's always-open SSE stream making Playwright's `networkidle`
unreachable — the same fact the kanban specs already recorded for the board.
The opt-in payroll-WRITE specs first stopped on the documented operator-action
condition (the standing draft locking leave changes; the app refused with the
delete-this-draft remedy verbatim — the refusal path proving itself), and once
the owner deleted the draft, the primary write spec passed: a week posted
through the browser, read back from Xero's own records. The re-posting specs
then exhausted the tenant's daily quota — one day's allowance covers roughly
two full integration suites plus several live reruns and one E2E write pass,
a budget worth knowing before scheduling the release-candidate evidence run.
An exhausted quota reads as a code regression unless you know the signature:
every Xero-touching spec fails at once (11 of 109 on 21 August), each one a
500 whose traceback ends in `RateLimitException`, with `X-Rate-Limit-Problem:
day` and a `Retry-After` of roughly eleven hours. Confirm it from the run's
own `logs/e2e/django.log` rather than bisecting — `grep -c RateLimitException`
against the count of `ERROR django.request Internal Server Error` settles it
in one command.

**Outbound links are probed from an authenticated context, 2026-08-22.** The
company-defaults screen shipped a link to `go.xero.com/Settings/InvoiceSettings/`,
a 404, and no tier could have caught it: nothing probed the URLs the app hands
to users. `scripts/ops/outbound_links_probe.py` now enumerates every outbound
target and verifies each by the strongest means available, with
`scripts/tests/test_outbound_links_integration.py` as the slow-tier merge
gate. Enumeration is structural so a new integration cannot be left out:
every `http(s)://` literal in the tree; every `URLField` on every first-party
model, found through Django's model registry; and every non-relation `*_id`
column, which is classified in the probe's registries (verifiable kind,
vendor id with no verifier yet, or not a link) — `unclassified_fields()` is
asserted empty by the hermetic unit suite, so an unclassified column is a
red commit. Its first run over the full inventory found 13 `URLField`s and
71 id columns, five of them link-holding fields the first hand-written
enumeration had missed (`Procedure.google_doc_url` among them — the SOP
documents, the very case the probe exists for). Measured facts that shaped it: `go.xero.com` and
`payroll.xero.com` route before they authenticate (a real page answers 302 to
the login, an unknown path a bare 404) but answer 503 to every HEAD, so the
probe is GET-only with the body unread; `portal.steelandtube.co.nz` likewise
answers 404 to HEAD and 200 to GET; Jira answers 202 and a login redirect to
any issue key, so Atlassian links are reported as unverifiable rather than
checked; Google's Drive API answers 404 for unshared files as well as missing
ones, so the identity asking (`--google-as delegated|service-account`) is an
explicit choice, never a fallback. The first full run against the dev instance
took 30s for 76 targets (the Xero calls serialise at one per second) and found
the invoice-settings link plus two rotted certbot raw URLs in
`scripts/server/server-setup.sh` (the files moved under `certbot/src/`).

**Integration credentials move off the environment, 2026-08-23.** The owner
ruled the shape for vendor credentials as integrations keep arriving: typed
columns on one `IntegrationSettings` singleton in `apps/core` for everything
the install has exactly one of, typed tables for the N-of integrations, and
never `CompanyDefaults` (its any-staff GET echoes every column). Row-per-
integration was weighed and rejected because its only honest form is generic
columns plus a JSON bag mypy cannot see into. `PhoneProviderSettings` is
replaced rather than joined by the new model, and `GOOGLE_MAPS_API_KEY` leaves
`.env`, `shared.env` and `server-setup.sh` entirely. ADR 0053 records the rules.

**E2E residue that came back, 2026-08-23.** `[TEST] Phone Owner B 514429`
reappeared after every E2E run although `e2e_cleanup` deleted it each time.
Every company a spec creates through the app becomes a Xero contact in the
demo organisation (80 of them by now), Xero contacts can only be archived, and
the contact sync is incremental by modification time — so any test contact
touched in Xero after the restored watermark is re-imported. Every confirmed
cleanup therefore archives the E2E contacts in Xero first (its production and
read-only guards run before any local delete, and the step runs even when the
local database is already clean — the normal state after a run; `diagnostics`
moved above the integrations in the layer contract so the cleanup can import
the archive seam rather than reach a second command by name), and a company archived in Xero is the organisation's mirror rather than
residue to the cleanup and the preflight; archived contacts stay importable
because invoice linkage fetches them on demand.

**Served but unreachable routes are gated, 2026-08-23.** `/purchasing/po` and
`/purchasing/stock` were served, specced and green for weeks while nothing in
the app linked to them: the PO specs navigate by `page.goto`, so a route can
pass its spec and be invisible to a user. `scripts/checks/route_reachability.py`
now enumerates every `createFileRoute` path and every in-app `to=`/`href=`/
`navigate`/`redirect` target and fails the integration tier on any route with
no target — the inverse of the outbound-link probe, which proves the URLs the
app emits resolve. The first run over the tree found exactly those two.

**The phone provider is proven against 2talk itself, 2026-08-23.**
`apps/crm/tests/test_phone_provider_integration.py` is the ADR 0050 gate for
the pull: it logs in with the `IntegrationSettings` credentials the app
resolves, imports a seven-day window through `sync_call_history`, reads every
call and recording back from the database and the archive, streams one
through the download endpoint, and pulls the window again to prove the second
pass is a no-op. The hermetic guard now refuses the phone client's transport
in unit tests, and the test database copies the real `PhoneEndpoint`s so a
direction assertion means something. Three facts only the real portal could
supply: the first real sync failed on a withheld caller, which 2talk reports
as origin `""` and the CRM normaliser now answers with NULL; the CDR mixes
billing lines (type "Add-On", no parties, status NULL) in with calls, which
`is_call_payload` drops; and in 45,637 real payloads a call never has a blank
`type`, `status` or `description`. Playing a real recording in the browser
found a fourth: through a compressing proxy the strong ETag arrives weakened
to `W/"<sha>"`, and the download endpoint's strict string compare answered
200 and resent the audio on every replay — RFC 9110 makes `If-None-Match` a
weak comparison, and Django's `get_conditional_response` now does it. The
throwaway Playwright driver that found that is deleted: a scratch script is
the ad-hoc probe ADR 0050 forbids as verification, and the unit test carries
the weak-validator case instead. Provider-side deletion (`deleteMedia`) stays
outside the gate by owner ruling: it is irreversible on the one live account
and 2talk offers no undo, the ADR's sole opt-in exception.

**A recording's length is measured when it is archived, 2026-08-24.** The
calls page player read `0:00` until played: it is `preload="none"` by design
(one player per row; metadata preload fetched every recording on load), and a
native control cannot be told a length it has not fetched. The length the
call row already held could not stand in — 2talk's CDR `seconds` is billed
per started minute (660 / 360 / 120 on real rows whose recordings run 616 /
304 / 110 / 71 s). `PhoneCallRecording.duration_ms` is now measured from the
bytes at archive time (tinytag, MIT; mutagen rejected as GPL, ffprobe as not
a Python dependency), backfilled by migration for every archived file present
on the host, and stated by a small shared `AudioPlayer` before anything is
fetched; the element's own duration takes over once it has loaded. The
archive now refuses bytes it cannot measure, which turned the fake
`b"recorded audio"` in three unit tests into real WAVs from one generator,
`apps.core.test_data.silent_wav`, shared with the E2E seed.

**"Duplicate" call rows are the provider's per-leg CDR, read properly now,
2026-08-24.** 2talk logs one row per call LEG: a forwarded call is an inbound
row to the office line plus an outbound diversion row to the forward target,
each with its own recording (same length, near-identical audio by waveform
correlation, different bytes); an unanswered burst is two or three rows
identical in everything but the provider's row id. One three-day pull held 36
recorded diversion pairs, 57 identical Busy pairs and 46 identical triples.
v1 stored and showed all of them undifferentiated. Two readings fix it:
the forward target (a staff mobile) is registered as a `PhoneEndpoint`, so
diversion legs classify inbound under the caller's number and rematch did
132 historical legs; and the calls list collapses indistinguishable
unrecorded, job-less rows to the smallest id wearing an `attempt_count` —
ingest still keeps every provider row, recorded legs never collapse (a
recording is evidence only its own row holds), and a job-linked row is never
suppressed. The nullable identity columns match through Coalesce-to-"" keys
because SQL NULL never equals NULL, and "" cannot collide with data ADR 0040
bans from those columns.

**Process forms slice complete, 2026-08-25.** A stored, exclusive `category`
field on `Form` (and `Procedure`) replaced v1's overlapping tags-array
filter, so a document that carried more than one matching tag — incident
forms 202/205, tagged both safety and incident — no longer lists twice.
Every entry write and archive is recorded on `ProcessEvent`, the domain's
own append-only audit trail (`JobEvent`'s shape without the optimistic-
concurrency machinery a form entry does not need). Acknowledgements are a
dedicated append-only record (`Acknowledgement`): a self-only "I have read
this" receipt per staff member per form, never an inference over
`ProcessEvent`. Design doc:
`docs/superpowers/specs/2026-08-25-process-documents-design.md`.

**The real production procedures verified through the slice's seams,
2026-08-26.** With the production service-account key
(`gcp-credentials-prod.json`, gitignored in the repo root), the outbound-link
probe asked Drive for every one of the 54 restored `Procedure.google_doc_id`
rows — first as the raw production service account, then delegated as the
real Workspace user (`--google-as delegated` with `GCP_DELEGATED_SUBJECT`,
since the scrubbed dev `company_email` is a placeholder). Both identities
agree: 46 docs answer, 8 are broken, and the delegated run also proved the
three gdocs-manifest docs a service-account run cannot see. The restore and
category backfill hold on real data — 54 rows, zero NULL categories
(43 safety, 9 reference, 1 training, 1 jsa) — and the scrubber's
titles-are-metadata policy is confirmed intact (`site_location` is the one
anonymised field). The 8 broken rows are production data rot, not a code
defect: Doc.363 Milling Machine SOP is **trashed** (restorable from Drive
trash), and seven H&S admin docs are gone even to the Workspace owner —
Health & Safety Annual Tasks Ongoing 2017, MSM Health & Safety Annual Plan,
Maintenance Inspection Procedures v2, MSM Health and Safety Statement, MSM
Health and Safety Policy, MSM Health Safety System - latest, MSM Health
Safety Document List. The fix task is in `rewrite-status.md`.

**Staff need at least one email address; either one signs them in,
2026-08-26.** Owner ruling from UAT of the process-forms slice (which hit
"Office email is required" creating a wage worker): `office_email` and
`payroll_email` are both individually optional, a database constraint
(`staff_at_least_one_email`) requires one of them, and the existing
dual-match login backend accepts either. The field names are deliberately
kept — only the requiredness was wrong. An earlier same-day ruling to invert
the rule (payroll required, USERNAME_FIELD swap, backfill) was superseded:
it would have forced inventing payroll addresses for the nine
admin/system/office rows that lack one. Two adjacent defects fixed with it:
the scrubber excluded the automation account by email, which silently
dropped NULL-office-email rows from the identity scrub (SQL NULL
semantics), and it never scrubbed `payroll_email` at all — it now excludes
by pk and scrubs a set payroll address while preserving NULL shape.

**The flip and its triage, 2026-08-29.** Production cuts over to v2 the
night of 2026-08-29; v1 is never deployed again unless something goes very
wrong, with `rollback-instance.sh` plus the preserved v1-final database as
the escape hatch and Monday 07:00 as the decide-by point. Owner triage the
same day: the weak-password path, AccessLogging/DisallowedHost, the
one-implementation gate expansion and the 500-line passes are DEFERRED —
large refactors days before a flip add regression risk and remove none.
The `production` branch tracks main's flip SHA (`bfaba5d`).

**Prod backups had two upload paths; only the undocumented one worked,
2026-08-29.** The systemd `backup-db-msm-prod` unit failed nightly since at
least July: its per-instance rclone remote was a bare service account,
which has zero My-Drive quota, so every upload 403s — a config that had
been hand-fixed on 2026-07-02 and silently regenerated broken by the
2026-08-08 deploy from a stale credentials file. The real off-site copies
rode a root crontab (00:00 dump, 00:10 cleanup-as-root) whose rclone config
holds a personal OAuth token. Durable fix shipped in PR #105: a
service-account remote without a shared drive is refused at render time,
`BACKUP_GDRIVE_TEAM_DRIVE_ID` is a required credentials value, and
`verify-instance.sh` round-trips a probe upload as the instance user. The
same PR retired the `.sha` release-pointer sidecar (consumed by nothing)
for the `.migrations.json` snapshot restores actually read, through one
shared producer. The Morris Sheetmetal Admin shared drive
(`0AIH4oBEFMDckUk9PVA`) is proven writable by the instance service account;
an independent copy of the 2026-08-29 dump sits there.

**A cutover-host.sh re-run locked the UAT host out for 9.5 hours,
2026-08-29.** The re-run (done for the repo-remote swap) flushed INPUT
under an active ufw, deleting the six jumps into the ufw-* chains while
leaving the chains. ufw derives `Status: active` from chain existence, and
while its chains exist every ufw command — default, allow, `--force
enable`, reload, disable+enable, `ufw-init force-reload` — skips rule
installation, so `ufw default deny incoming` in the following
server-setup.sh converge set INPUT policy DROP with no
established-connections rule, no allows and no logging: every inbound
packet and every reply to outbound traffic silently dropped, `ufw status`
green throughout. Only a reboot (boot-time install from a chainless
kernel) or deleting every ufw chain then enabling recovers; all facts
reproduced in a NET_ADMIN container on the host
(`scripts/server/test_ufw_lockout_guard.sh` pins them). Recovery was an
OCI SOFTRESET; the persisted ufw config was always correct. Durable fix:
`assert_ufw_effective` (`common.sh`) checks the INPUT jump — never `ufw
status` — before server-setup.sh touches ufw and after it enables it, and
cutover-host.sh refuses to run at all once ufw is active. Exonerated by
evidence: the Deploy-to-UAT workflow, fail2ban, the rpcbind change and
the OCI network.

**UAT integration triage corrected two false premises and exposed the real
credential gaps, 2026-08-30.** The Maps key existed only in v1's runtime env,
never its database, so the durable fix is a required per-instance credential
plus a live probe inside `verify-instance.sh`. A real cutover preserves the
plaintext `workflow_xeroapp` token row; UAT needed OAuth only because its
scrubbed source deliberately removed that row. The migration did carry Fernet
ciphertext for the phone and supplier credentials into plaintext columns, so
it now clears those groups for trusted fixture reload or explicit re-entry.
The adjacent classifications were corrected at the same time: outgoing email,
AI product work and session-replay capture are deferred rather than retired,
and replay purge is not scheduled before any ingestion path exists. The AI
gateway/provider plumbing remains because deferred features share it. The
observed Celery Beat startup delay and fresh in-code schedule tables required
no fix.

**Beat's schedule shelve and the verifier's crash-loop blindness, 2026-08-30.**
Celery beat's PersistentScheduler writes its last-run shelve file to CWD, and
every rendered beat unit set WorkingDirectory to the `app` symlink into the
immutable release dir, so beat crash-looped on permission denied on every
instance created since releases became immutable (msm-uat reached
NRestarts>1900). verify-instance.sh reported it healthy anyway: with
Restart=always/RestartSec=10 a crash-looping unit is "active" for a slice of
every cycle, so a bare is-active check passes intermittently — a verifier
bug, not a flake. Durable fixes: the unit template passes
`--schedule=<instance root>/celerybeat-schedule` (pinned by the template
test), and the verifier requires NRestarts unchanged across a 12s window
plus a recheck at the end of the run; the window and the templates'
RestartSec values are pinned as a pair. Celery ships no sd_notify, so a
readiness signal was not an available alternative.

**Copy from Estimate was never ported, and the restore made it atomic,
2026-08-31 (KAN-346).** A prod report surfaced that v1's Quote-tab "Copy from
Estimate" button had no v2 equivalent: the tab was rebuilt lean, the button
had no E2E spec to miss it, and no ledger recorded the drop. v1 implemented
it as a client-side loop (fetch estimate lines, delete quote lines, create
each), so a mid-flight failure left a half-copied quote; v2 restores it as
one server call (`copy_from_estimate`, sharing the creation-time seeding's
copy loop). Rulings made with the owner: a blank quote — every line totalling zero cost
and zero revenue, which is what the $0 creation seed produces — is replaced
silently with no revision recorded; blankness is judged per line TOTAL (the
seed's time lines carry real rates at quantity 0, so a unit-price test
wrongly called the seed priced — caught by the E2E gate), never the set's
total, so offsetting adjustments still archive; a priced quote
answers 409 and the UI offers archive-and-replace through the existing quote
revision machinery; and a quote already matching the estimate answers as a
no-op so a double press cannot stack identical archives.

**A partial singleton save cannot trigger consequences for an excluded field,
2026-09-01 (KAN-350).** Production proved the hourly Xero completion stamp held
a stale `CompanyDefaults` instance: `update_fields` protected the current
`labour_cost_loading` column while the model override still recomputed every
Staff wage rate from its old in-memory value. The override now treats
`update_fields` as write intent before comparing or propagating the loading.
The adjacent employee mirror also stops rewriting unchanged Staff and payroll
terms every hour: Xero supplies `Employee.updatedDateUTC`, but the separately
fetched salary and working-pattern resources have no modification timestamp,
so Staff materialises a canonical checksum of the complete enriched Xero
projection. A no-op requires both that stored digest and the current local
projection to match, so a stale digest cannot hide local drift.

**Access logging lands, and two v1 shapes that do not survive the port,
2026-09-02.** The per-request access line is back, on its own `access` logger
routed to the console: v1 gave it a rotating `access.log`, but journald already
rotates, retains and greps, and a file handler would only put a second copy on
disk for an operator to find and prune. Two v1 constructs were deliberately not
carried across. First, `AccessLoggingMiddleware` must read the principal AFTER
calling `get_response`. v1 checked `request.user.is_authenticated` on the way in
and returned early when anonymous, which under ninja auth — it sets
`request.user` during operation dispatch, after every middleware has run —
would have logged nothing for any `/api/**` request, that is, for the whole
application, while a v1-shaped test still passed. Second,
`DisallowedHostMiddleware` never worked: `process_exception` fires only for
exceptions raised by the view, and `DisallowedHost` comes out of
`CommonMiddleware.process_request` above it. Django's own handler was returning
the 400 in v1 too; only the traceback was ever the complaint, so v2 keeps the
`django.security.DisallowedHost` record and strips its traceback with a logging
filter. The middleware's JWT re-authentication block went with it — v2 is
cookie-authenticated — and with it a bare `except Exception: pass`.

**Two Jira tickets were closed with no commit behind them, 2026-09-02.** KAN-339 (the
overtime repair commands price 1.5x/2x pay-item lines at the base wage) and KAN-354 (the
pay-run mirror deletes history it never fetched) are both marked Done, and neither defect
is fixed in the code. Recorded because a Done ticket is normally the strongest evidence a
thing is finished, and here it is worth nothing; the tasks live on in `rewrite-status.md`
saying so.

**The 500-line baseline moved the wrong way, 2026-08-16 to 2026-09-02.** 42 production
and 21 test Python files over the limit became 43 and 26, with ten handwritten frontend
files the original baseline never counted. `apps/job/services/job_service.py` grew 2,837
→ 3,044 and `apps/job/api.py` 1,810 → 1,863; twelve files now exceed 1,000 lines. Two
weeks of ordinary slices with no gate is what that costs, which is the argument for
adding one rather than against it.

**Maestral paused for 26 hours without dying, 22–23 August 2026.** A transient Dropbox
API error paused sync while the process stayed alive, so `systemctl` reported active and
`Restart=always` never fired. The generalisable fact — liveness is not health for a
sync daemon — is why the unbuilt alert in `rewrite-status.md` is specified against
`maestral status` output rather than the process.

**Session replay shipped 2026-09-02**, closing the storage decision this rewrite had
deferred: chunk payloads go to a private disk root, the rows index the store rather than
being it, and the purge is scheduled and deletes payloads. It is recorded here because
two `blocked-by:` rows in `v1-disposition.md` were waiting on that decision and their
disposition changes as a result.

**A replay cannot be made small, measured 2026-09-03.** Recordings from the development
database, served through `recording_events` and gzipped as the wire carries them: 162
events = 1.77 MB raw / 162 KB gzipped; 592 = 3.84 MB / 334 KB; 1,180 = 5.35 MB / 557 KB.
Across 14,891 stored chunks the largest single chunk is 940,739 bytes **already
compressed** (mean 22,888), so one rrweb full-snapshot event exceeds the E2E wire guard's
100 KB cap on its own and no chunk window, page or byte range can satisfy it. That is why
`/api/session-replays/recordings/{id}/events/` is exempted per-spec in
`session-replay.spec.ts` rather than made to fit, and why the page must not fetch a replay
until asked. Serialisation on the same 4.28 MB payload: `validate_python` 0.813s,
`dump_json` 0.283s, `json.dumps` 0.133s, gzip level 6 0.049s — the compression everyone
assumes is the cost is 5% of it.

