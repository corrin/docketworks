"""CLI harness for the AI quoting chat.

Sends one message through the LLM gateway in the context of a job's stored
quote-chat history and prints the reply, for end-to-end debugging of the
quoting-chat pipeline from a shell.

Ported from v1's ``test_gemini_chat``, renamed for two reasons: the gateway
routes to whichever provider is configured, so "gemini" would be a lie half
the time; and a ``test_*.py`` filename under ``apps/`` is collected by pytest.
v1 drove its ``ChatService`` (tool calls, mode responses, persistence); that
service is not ported, so the harness talks to the gateway directly and
persists nothing — a debugging probe, not a mutation (the future chat service
owns message persistence).
"""

from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.ai.enums import AIProviderTypes
from apps.ai.services.llm_client import LLMConfigurationError, chat_completion
from apps.core.errors import persist_app_error
from apps.job.models import Job, JobQuoteChat

SYSTEM_PREAMBLE = (
    "You are a quoting assistant for a sheet-metal fabrication workshop. "
    "Answer the user's final message in the context of the job and the "
    "conversation so far."
)


def build_prompt(job: Job, history: list[JobQuoteChat], user_message: str) -> str:
    """Assemble one flat prompt from job context, stored history and the message.

    Flat text rather than a messages array because the gateway's contract is a
    single user-role prompt (``chat_completion``); a per-role message list is
    the future chat service's concern.
    """
    lines = [SYSTEM_PREAMBLE, "", f"Job: {job.name}"]
    if job.description:
        lines.append(f"Job description: {job.description}")
    if history:
        lines.append("")
        lines.append("Conversation so far:")
        lines.extend(f"{message.role}: {message.content}" for message in history)
    lines.extend(["", f"user: {user_message}"])
    return "\n".join(lines)


class Command(BaseCommand):
    """Send one quoting-chat message for a job and print the model's reply."""

    help = "Sends one message through the AI quoting chat for a job and prints the reply."

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the job id, the message, and the optional provider override."""
        parser.add_argument("job_id", type=str, help="The UUID of the job to test the chat with.")
        parser.add_argument("message", type=str, help="The message to send to the AI assistant.")
        parser.add_argument(
            "--provider-type",
            type=str,
            choices=[choice.value for choice in AIProviderTypes],
            help="Route to a specific configured provider instead of the default one",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Fetch the job, build the prompt, call the gateway, print the reply."""
        job_id = options["job_id"]
        user_message = options["message"]
        provider_type = options["provider_type"]
        if not isinstance(job_id, str):
            raise TypeError("The job_id argument must be a string")
        if not isinstance(user_message, str):
            raise TypeError("The message argument must be a string")
        if provider_type is not None and not isinstance(provider_type, str):
            raise TypeError("The provider-type option must be a string")

        try:
            job = Job.objects.get(id=job_id)
        except Job.DoesNotExist as exc:
            raise CommandError(f'Job with ID "{job_id}" does not exist.') from exc

        history = list(job.quote_chat_messages.order_by("timestamp"))
        prompt = build_prompt(job, history, user_message)

        self.stdout.write(self.style.SUCCESS(f"--- AI chat harness for job: {job.name} ---"))
        self.stdout.write(f"Stored history messages: {len(history)}")
        self.stdout.write(f"User message: '{user_message}'")
        self.stdout.write(self.style.HTTP_INFO("Sending prompt to the LLM gateway..."))

        try:
            reply = chat_completion(prompt, provider_type=provider_type)
        except LLMConfigurationError as exc:
            # Operator-facing refusal: the fix is an AIProvider row, not a stack trace.
            raise CommandError(f"AI provider configuration error: {exc}") from exc
        except Exception as exc:
            persist_app_error(exc)
            raise

        self.stdout.write(self.style.SUCCESS("--- AI response ---"))
        self.stdout.write(reply)
        self.stdout.write(self.style.SUCCESS("--- End response ---"))
