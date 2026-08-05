"""AI integration model exports.

The concrete models pin their ``workflow_*`` table names because data restores
depend on those stable database identifiers.
"""

from .ai_provider import AIProvider
from .notebook_lm_link import NotebookLmLink

__all__ = [
    "AIProvider",
    "NotebookLmLink",
]
