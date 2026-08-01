"""Session replay models, ported from v1's ``apps/workflow/models/``.

Both models left v1's ``workflow`` app, so each pins
``Meta.db_table = "workflow_<modelname>"`` per the v2 porting rules.
"""

from .session_replay import SessionReplayChunk, SessionReplayRecording

__all__ = [
    "SessionReplayChunk",
    "SessionReplayRecording",
]
