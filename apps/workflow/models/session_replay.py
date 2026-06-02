import uuid

from django.conf import settings
from django.db import models


class SessionReplayRecording(models.Model):
    """A browser session replay recorded by rrweb."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="session_replay_recordings",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    ended_at = models.DateTimeField(blank=True, null=True)
    initial_path = models.CharField(max_length=500)
    latest_path = models.CharField(max_length=500)
    job_id = models.UUIDField(blank=True, null=True, db_index=True)
    user_agent = models.TextField(blank=True)
    viewport_width = models.PositiveIntegerField(blank=True, null=True)
    viewport_height = models.PositiveIntegerField(blank=True, null=True)
    event_count = models.PositiveIntegerField(default=0)
    compressed_bytes = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]
        indexes = [
            models.Index(
                fields=["user", "-started_at"],
                name="workflow_replay_user_start_idx",
            ),
            models.Index(
                fields=["started_at"],
                name="workflow_replay_started_idx",
            ),
            models.Index(
                fields=["job_id", "-started_at"],
                name="workflow_replay_job_start_idx",
            ),
        ]


class SessionReplayChunk(models.Model):
    """Compressed rrweb event batch for a recording."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    recording = models.ForeignKey(
        SessionReplayRecording,
        on_delete=models.CASCADE,
        related_name="chunks",
    )
    sequence = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    first_event_timestamp_ms = models.BigIntegerField()
    last_event_timestamp_ms = models.BigIntegerField()
    event_count = models.PositiveIntegerField()
    compressed_bytes = models.PositiveIntegerField()
    storage_path = models.CharField(max_length=500)
    sha256 = models.CharField(max_length=64)
    path = models.CharField(max_length=500)
    job_id = models.UUIDField(blank=True, null=True, db_index=True)
    viewport_width = models.PositiveIntegerField(blank=True, null=True)
    viewport_height = models.PositiveIntegerField(blank=True, null=True)

    class Meta:
        ordering = ["recording_id", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["recording", "sequence"],
                name="workflow_session_replay_chunk_recording_sequence_uniq",
            )
        ]
        indexes = [
            models.Index(
                fields=["recording", "sequence"],
                name="workflow_chunk_record_seq_idx",
            ),
            models.Index(
                fields=["created_at"],
                name="workflow_chunk_created_idx",
            ),
        ]
