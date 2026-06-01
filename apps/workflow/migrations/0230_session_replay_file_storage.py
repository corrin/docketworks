import hashlib
import os
from pathlib import Path

from django.conf import settings
from django.db import migrations, models


def _storage_root() -> Path:
    return Path(settings.SESSION_REPLAY_STORAGE_ROOT).resolve()


def _relative_chunk_path(recording_id, sequence: int) -> str:
    return f"{recording_id}/{sequence:06d}.json.gz"


def _full_chunk_path(relative_path: str) -> Path:
    root = _storage_root()
    full_path = (root / relative_path).resolve()
    if not full_path.is_relative_to(root):
        raise ValueError("Replay chunk storage path escapes storage root")
    return full_path


def _write_existing_blob(relative_path: str, payload: bytes) -> None:
    full_path = _full_chunk_path(relative_path)
    full_path.parent.mkdir(parents=True, exist_ok=True)
    if full_path.exists():
        existing_hash = hashlib.sha256(full_path.read_bytes()).hexdigest()
        payload_hash = hashlib.sha256(payload).hexdigest()
        if existing_hash == payload_hash:
            return
        raise FileExistsError(f"Replay chunk file already exists: {relative_path}")

    temp_path = full_path.with_name(f".{full_path.name}.{os.getpid()}.tmp")
    try:
        with open(temp_path, "xb") as destination:
            destination.write(payload)
        os.replace(temp_path, full_path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def migrate_chunks_to_files(apps, schema_editor):
    SessionReplayChunk = apps.get_model("workflow", "SessionReplayChunk")
    for chunk in SessionReplayChunk.objects.select_related("recording").iterator():
        payload = bytes(chunk.events_gzip)
        relative_path = _relative_chunk_path(chunk.recording_id, chunk.sequence)
        _write_existing_blob(relative_path, payload)
        chunk.storage_path = relative_path
        chunk.sha256 = hashlib.sha256(payload).hexdigest()
        chunk.save(update_fields=["storage_path", "sha256"])


def migrate_chunks_to_db(apps, schema_editor):
    SessionReplayChunk = apps.get_model("workflow", "SessionReplayChunk")
    for chunk in SessionReplayChunk.objects.iterator():
        chunk.events_gzip = _full_chunk_path(chunk.storage_path).read_bytes()
        chunk.save(update_fields=["events_gzip"])


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("workflow", "0229_seed_session_replay_purge_schedule"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sessionreplaychunk",
            name="events_gzip",
            field=models.BinaryField(null=True),
        ),
        migrations.AddField(
            model_name="sessionreplaychunk",
            name="storage_path",
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="sessionreplaychunk",
            name="sha256",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.RunPython(migrate_chunks_to_files, migrate_chunks_to_db),
        migrations.AlterField(
            model_name="sessionreplaychunk",
            name="storage_path",
            field=models.CharField(max_length=500),
        ),
        migrations.AlterField(
            model_name="sessionreplaychunk",
            name="sha256",
            field=models.CharField(max_length=64),
        ),
        migrations.RemoveField(
            model_name="sessionreplaychunk",
            name="events_gzip",
        ),
    ]
