# 0054 — A screen is tested at the volume production gives it

Every screen that renders a collection is tested against the row count production actually
holds. A list behaves differently at three rows than at three thousand — it clips at the fold,
it needs a second page, its per-row query multiplies, its response crosses a wire limit — so a
green suite run on a thin table has not exercised the screen the business uses.

`docs/prod-data-shape.yml` is the committed record of that volume, one line per model, counts
only. `scripts/checks/data_shape_gap.py` names the tables the local database is too thin to
exercise, and `run_e2e.sh` prints it before every suite run.

ADR 0025 decides which regression a test guards and ADR 0052 whether the assertion can see it.
This one decides **whether the data can produce it at all** — an assertion that is correct and
falsifiable still proves nothing about a screen it never drove past one page.

## Rules

- **Read the shape before building a collection screen.** `docs/prod-data-shape.yml` is the
  authority on how many rows a screen will meet. A design that is fine at the local count and
  unusable at the production one is a defect already written; the number is knowable before
  the code is.
- **A volume-sensitive property is asserted in a way that holds at any row count.** Bounded and
  scrollable rather than clipping; a running count that names the *server's* total; a page size
  the client honours. Assertions of the form "there is a second page" test the environment
  instead of the code, and fail on a machine whose corpus is thin for reasons of its own —
  retention windows, a scrub, a fresh instance. State the mechanism, not the symptom.
- **Where the property only exists above a threshold, the spec seeds past it.** Paging, infinite
  scroll and virtualisation have nothing to assert below one page, so the spec that asserts them
  creates the rows it needs rather than hoping the environment supplies them. Hoping is how a
  suite goes green on a corpus that shrank.
- **Volume is necessary and not sufficient.** The defect that produced this ADR shipped on a
  database already holding hundreds of the rows in question: nothing looked at the pane. Data
  makes a defect *reachable*; only an assertion makes it *caught*. Never argue that a
  representative corpus removes the need for the assertion, or that the assertion removes the
  need for the corpus.
- **A thin table is reported, never baselined.** The gap check prints; it does not gate. A
  threshold that admits today's shortfalls is a baseline, and this repository does not keep
  baselines — the number is there to move. What gates is the spec: a spec asserting a
  volume-sensitive property on a thin table owns seeding it first.
- **Re-capture the shape when the answer would change a decision**, with
  `manage.py data_shape --instance <name>` against a production instance. Counts only ever
  leave that instance, so the file stays reviewable and safe to commit. A stale shape is still
  better than a local guess, and the `captured_at` field is what says how stale.
- **Some corpora are bounded by policy, not by growth.** Session replays live inside a retention
  window, so their production count is a moving ceiling rather than an ever-rising floor. Read
  what bounds a table before treating its production count as a target.
