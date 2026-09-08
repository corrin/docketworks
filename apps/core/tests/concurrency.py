"""Real PostgreSQL contention observed through the blocking backend identities."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from queue import Queue
from time import monotonic, sleep

from django.db import connection, connections


def start_database_task[T](
    pool: ThreadPoolExecutor, action: Callable[[], T]
) -> tuple[Future[T], int]:
    """Run an action on its own connection and expose its backend PID."""
    pids: Queue[int] = Queue()

    def run() -> T:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_backend_pid()")
                pids.put(cursor.fetchone()[0])
            return action()
        finally:
            connections.close_all()

    pending = pool.submit(run)
    return pending, pids.get(timeout=10)


def await_database_lock[T](pending: Future[T], worker_pid: int) -> None:
    """Wait until this transaction demonstrably blocks the worker, or fail."""
    deadline = monotonic() + 10
    while True:
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid() = ANY(pg_blocking_pids(%s))", [worker_pid])
            if cursor.fetchone()[0]:
                return
        if pending.done():
            pending.result()
            raise AssertionError("The worker completed without waiting for this transaction.")
        if monotonic() >= deadline:
            raise AssertionError("The worker did not wait for this transaction's lock.")
        sleep(0.01)
