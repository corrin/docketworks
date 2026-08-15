"""The Xero sync run lock: its key, its timeout, and how it is released.

Lives in its own module so every holder of the lock — ``sync_service`` (the
dispatcher), ``sync_worker`` (the Celery task) and the ``start_xero_sync``
command — can import it without creating a cycle: dispatcher -> worker ->
service-class would otherwise loop.
"""

from django.core.cache import caches

# The lock is cross-process (Celery worker writes, gunicorn SSE views read),
# so it lives on the Redis-backed "shared" alias, never the per-process
# LocMem default.
_sync_cache = caches["shared"]

SYNC_STATUS_KEY = "xero_sync_status"
LOCK_TIMEOUT = 60 * 60 * 4  # 4 hours


def release_sync_lock(owner: str) -> bool:
    """Release the sync lock only if ``owner`` still holds it.

    Owner-checked, like the token refresh lock in ``auth.py``: a run that
    outlives LOCK_TIMEOUT no longer owns the key, and deleting it
    unconditionally would free the NEXT run's lock and permit exactly the
    concurrent sync the lock exists to prevent. Returns whether it deleted.

    The get-then-delete is deliberately not atomic. It could only lose a race
    if the lease expired under a live run, and the worker renews the lease on
    every progress event, so that window is not reachable while a run is
    making progress. Do not add a compare-and-delete Lua script or a
    django-redis Lock for it: django-redis is not installed, the "shared"
    alias is LocMemCache under test settings, and the lock VALUE is the run's
    task id — the routing key for the progress-stream cache keys and the
    ``task_id`` the API hands clients — so it cannot become an opaque token.
    """
    if _sync_cache.get(SYNC_STATUS_KEY) != owner:
        return False
    _sync_cache.delete(SYNC_STATUS_KEY)
    return True
