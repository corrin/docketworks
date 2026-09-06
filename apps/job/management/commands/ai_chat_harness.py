"""Exercise the production ChatKit pipeline from the CLI."""

from uuid import UUID

from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand, CommandError, CommandParser

from apps.ai.enums import AIProviderTypes
from apps.job.chat.conversation import send_message
from apps.job.chat.store import ChatContext
from apps.job.models import Job


class Command(BaseCommand):
    """Send a persisted quoting message, optionally continuing a named thread."""

    help = "Send and persist a quoting-chat message using the same pipeline as the job tab."

    def add_arguments(self, parser: CommandParser) -> None:
        """Require a job and message; a thread id explicitly selects existing history."""
        parser.add_argument("job_id", type=UUID)
        parser.add_argument("message")
        parser.add_argument("--thread-id")
        parser.add_argument(
            "--provider-type",
            default=AIProviderTypes.OPENAI,
            choices=[choice.value for choice in AIProviderTypes],
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Validate CLI scope before invoking ChatKit's durable message path."""
        job_id = options["job_id"]
        message = options["message"]
        thread_id = options["thread_id"]
        provider_type = options["provider_type"]
        if not isinstance(job_id, UUID) or not isinstance(message, str):
            raise TypeError("The job id must be a UUID and the message must be text")
        if thread_id is not None and not isinstance(thread_id, str):
            raise TypeError("The thread id must be text")
        if not isinstance(provider_type, str):
            raise TypeError("The provider type must be text")
        if not Job.objects.filter(id=job_id).exists():
            raise CommandError(f'Job with ID "{job_id}" does not exist.')
        context = ChatContext(job_id=job_id, provider_type=provider_type)
        reply = async_to_sync(send_message)(context, message, thread_id)
        self.stdout.write(reply)
