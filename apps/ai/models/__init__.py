"""AI integration models, ported from v1's ``apps/workflow/models/``.

Both models left v1's ``workflow`` app, so each pins
``Meta.db_table = "workflow_<modelname>"`` per the v2 porting rules.
"""

from .ai_provider import AIProvider
from .notebook_lm_link import NotebookLmLink

__all__ = [
    "AIProvider",
    "NotebookLmLink",
]
