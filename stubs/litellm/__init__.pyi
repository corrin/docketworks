"""Minimal typing stub for the litellm surface apps.quoting.services.llm_client uses.

litellm ships no py.typed marker, and only ``completion()`` plus the response
shape below are reached from v2. Kept deliberately narrow: widening this stub
means widening the LLM boundary, which should be a deliberate decision.
"""

from collections.abc import Sequence
from typing import Any

suppress_debug_info: bool

class Message:
    content: str | None

class Choice:
    message: Message

class ModelResponse:
    choices: Sequence[Choice]

def completion(
    *,
    model: str,
    messages: Sequence[dict[str, Any]],
    api_key: str,
    temperature: float | None = ...,
    max_tokens: int | None = ...,
) -> ModelResponse: ...
