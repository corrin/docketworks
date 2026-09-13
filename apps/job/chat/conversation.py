"""CLI access to the same ChatKit conversation pipeline used by the browser."""

from chatkit.server import StreamingResult
from chatkit.types import (
    AssistantMessageItem,
    ErrorEvent,
    InferenceOptions,
    ThreadAddUserMessageParams,
    ThreadCreateParams,
    ThreadItemDoneEvent,
    ThreadsAddUserMessageReq,
    ThreadsCreateReq,
    ThreadStreamEvent,
    UserMessageInput,
    UserMessageTextContent,
)
from pydantic import TypeAdapter

from apps.job.chat.server import chat_server
from apps.job.chat.store import ChatContext


class ChatResponseError(RuntimeError):
    """A failed assistant run reported by the ChatKit stream."""


EVENT_ADAPTER: TypeAdapter[ThreadStreamEvent] = TypeAdapter(ThreadStreamEvent)


async def send_message(context: ChatContext, content: str, thread_id: str | None = None) -> str:
    """Persist a turn through ChatKit, returning its completed assistant messages."""
    message = UserMessageInput(
        content=[UserMessageTextContent(text=content)],
        attachments=[],
        inference_options=InferenceOptions(),
    )
    request: ThreadsCreateReq | ThreadsAddUserMessageReq
    if thread_id is None:
        request = ThreadsCreateReq(params=ThreadCreateParams(input=message))
    else:
        request = ThreadsAddUserMessageReq(
            params=ThreadAddUserMessageParams(input=message, thread_id=thread_id)
        )
    result = await chat_server.process(request.model_dump_json(), context)
    if not isinstance(result, StreamingResult):
        raise TypeError("A chat message must produce a streaming response")
    replies: list[str] = []
    async for frame in result:
        # GPT: These are complete frames emitted by ChatKitServer, not arbitrary network chunks.
        event = EVENT_ADAPTER.validate_json(frame.removeprefix(b"data: ").strip())
        if isinstance(event, ErrorEvent):
            raise ChatResponseError(event.message if event.message is not None else event.code)
        if isinstance(event, ThreadItemDoneEvent) and isinstance(event.item, AssistantMessageItem):
            replies.extend(part.text for part in event.item.content)
    if not replies:
        raise RuntimeError("The assistant finished without a text response")
    return "\n".join(replies)
