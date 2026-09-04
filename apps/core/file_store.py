"""Private on-disk file stores rooted at a configured directory.

Phone-call recordings and session replays both keep a metadata row in Postgres
and the payload on a private disk root, and v1 implemented that twice. The
properties worth having in one place are the ones that are easy to get subtly
wrong: a relative path may not escape the root, a write must be atomic so a
crashed process cannot leave a half-file that reads as valid, and a store that
indexes payloads by checksum must be able to refuse an overwrite rather than
silently replace a chunk another request already stored.
"""

import os
from pathlib import Path
from uuid import uuid4


class PrivateFileStore:
    """A directory tree that only this application writes to.

    ``label`` names the store in error messages: a path-escape failure is a
    bug report, and "session replay" versus "phone call recording" is the
    first thing its reader needs to know.
    """

    def __init__(self, *, root: str, label: str) -> None:
        """Resolve the configured root once; a relative root is a config bug."""
        if not root:
            raise ValueError(f"{label} storage root is not configured")
        self._root = Path(root).resolve()
        self._label = label

    @property
    def root(self) -> Path:
        """The resolved directory every path in this store lives under."""
        return self._root

    def full_path(self, storage_path: str) -> Path:
        """Resolve a relative path inside the root, refusing to escape it.

        Resolution happens before the check because ``..`` segments and
        symlinks only collapse once resolved; comparing the unresolved string
        would accept a path that lands outside the root.
        """
        full_path = (self._root / storage_path).resolve()
        if not full_path.is_relative_to(self._root):
            raise ValueError(f"{self._label} storage path escapes storage root: {storage_path}")
        return full_path

    def write(self, *, storage_path: str, payload: bytes, overwrite: bool) -> None:
        """Write payload atomically, optionally refusing an existing target.

        The write goes to a temporary name unique to this call and is renamed
        into place, so a reader never observes a partial file. ``overwrite`` is
        required rather than defaulted: for a checksum-indexed store, an
        existing target means two requests claimed the same slot, which the
        caller must hear about instead of losing one of them.

        Opus: the temp name is unique per call, not per process. Two threads
        writing one storage_path share a pid, so a pid-suffixed name is the
        same name for both: the loser's ``open("xb")`` raises and its cleanup
        removes the file the winner is still writing. Owning the temp name is
        what makes the unconditional cleanup below safe.

        Opus: ``overwrite=False`` is enforced by ``os.link``, not by the
        ``exists`` check above it. That check is a fast path with a clearer
        message, but between it and a rename another writer can take the same
        path and the rename replaces them silently — the exact loss the flag
        exists to prevent. ``link`` refuses an existing target in one
        filesystem operation, so the refusal is the same whoever else is
        running.
        """
        full_path = self.full_path(storage_path)
        if not overwrite and full_path.exists():
            raise FileExistsError(f"{self._label} file already exists: {storage_path}")

        full_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = full_path.with_name(f".{full_path.name}.{uuid4().hex}.tmp")
        try:
            with temp_path.open("xb") as destination:
                destination.write(payload)
            if overwrite:
                temp_path.replace(full_path)
            else:
                os.link(temp_path, full_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def read(self, storage_path: str) -> bytes:
        """Read a payload, failing loudly when the file has gone missing."""
        full_path = self.full_path(storage_path)
        if not full_path.exists():
            raise FileNotFoundError(f"{self._label} file missing: {storage_path}")
        return full_path.read_bytes()

    def delete(self, storage_path: str) -> None:
        """Remove a payload if it is there; a gone file is the wanted state."""
        self.full_path(storage_path).unlink(missing_ok=True)

    def remove_dir_if_empty(self, storage_path: str) -> None:
        """Drop a now-empty directory left behind by deleting its contents."""
        directory = self.full_path(storage_path)
        if not directory.is_dir():
            return
        if any(directory.iterdir()):
            # A concurrent write landed while the purge was deleting. Leaving
            # the directory is correct: the new file is live data.
            return
        directory.rmdir()
