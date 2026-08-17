"""What each cache alias promises, asserted where settings may be imported.

Opus: The domain apps cannot check this themselves: the layer contract puts `config`
on top, so a test in `apps/` may not read settings modules. It belongs here.
"""

from config import settings as production_settings


def test_shared_cache_spans_processes() -> None:
    """The "shared" alias exists to pair celery with the web process.

    Opus: Payroll progress is the case that proved it matters: the posting task
    publishes its events from the Celery worker and the SSE stream replays them
    from the web process. On a per-process backend the two are simply different
    caches, and the observed result was a payroll run that reached Xero in full
    while the operator watched a stream that could never emit — no results, no
    error, just a spinner, and every reason to post a second time.

    Opus: `settings_test` deliberately puts both aliases on LocMem because the suite
    is single-process, which is exactly why this reads the production module.
    """
    backend = production_settings.CACHES["shared"]["BACKEND"]

    assert "locmem" not in backend.lower(), (
        f"CACHES['shared'] is {backend}, which is per-process. Payroll progress — and "
        "anything else pairing celery with the web process — silently stops crossing, "
        "and the symptom is a UI that waits forever on work that already succeeded."
    )
