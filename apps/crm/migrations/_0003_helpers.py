"""The duration backfill rule, factored out of 0003 so it can be tested.

Lives inside ``migrations/`` rather than in the app for the reason
``_0002_helpers`` in quoting gives: a migration must not import app code,
which is free to change underneath a frozen historical record.
"""

import logging
from pathlib import Path
from typing import Any

from tinytag import TinyTag, TinyTagException

logger = logging.getLogger(__name__)


def measure_archived_recordings(model: Any, storage_root: Path) -> int:
    """Write ``duration_ms`` for every archived row whose file is present. Returns the count.

    A row whose file is missing keeps NULL: that is the same state the
    download endpoint reports as a 404, and inventing a length for it would
    be the read-side fallback ADR 0015 forbids. A file tinytag cannot read
    ABORTS the migration naming the row — it is not a recording, and a
    migration that skipped it would report success over a defect.
    """
    measured = 0
    rows = model._default_manager.filter(
        archived_at__isnull=False, storage_path__isnull=False, duration_ms__isnull=True
    )
    for recording in rows.iterator():
        path = storage_root / recording.storage_path
        if not path.exists():
            continue
        # tinytag raises on some junk and answers a None duration on the rest;
        # both mean this file is not a recording.
        try:
            tag = TinyTag.get(path)
        except TinyTagException as exc:
            raise RuntimeError(
                f"PhoneCallRecording {recording.pk}: {path} is not audio tinytag can measure"
            ) from exc
        if not tag.duration:
            raise RuntimeError(
                f"PhoneCallRecording {recording.pk}: {path} is not audio tinytag can measure"
            )
        recording.duration_ms = round(tag.duration * 1000)
        recording.save(update_fields=["duration_ms"])
        measured += 1
    logger.info("Measured %s archived phone recordings", measured)
    return measured
