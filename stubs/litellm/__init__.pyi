"""Minimal typing stub for the litellm surface apps.ai.services.llm_client uses.

GPT: This stub covers the gateway's completion and pricing surface; the Agents
SDK owns the asynchronous adapter. Keep signatures scoped to those consumers.
"""

from collections.abc import Sequence
from typing import TypedDict

suppress_debug_info: bool

class MessageParam(TypedDict):
    role: str
    content: str

class Message:
    content: str | None

class Choice:
    message: Message

class Usage:
    prompt_tokens: int
    completion_tokens: int
    def __init__(
        self,
        *,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        prompt_tokens_details: dict[str, int] | None = ...,
        reasoning_tokens: int | None = ...,
    ) -> None: ...

class ModelResponse:
    choices: Sequence[Choice]
    model: str
    usage: Usage
    def __init__(
        self, *, model: str, choices: Sequence[dict[str, object]], usage: Usage
    ) -> None: ...

def cost_per_token(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    usage_object: Usage,
) -> tuple[float, float]: ...
def completion(
    *,
    model: str,
    messages: Sequence[MessageParam],
    api_key: str,
    timeout: float | None = ...,
    temperature: float | None = ...,
    max_completion_tokens: int | None = ...,
) -> ModelResponse: ...
