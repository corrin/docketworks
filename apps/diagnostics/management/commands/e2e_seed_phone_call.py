"""Seed one recorded phone-provider call for the CRM phone-call spec.

The phone provider is a pull-only portal (apps/crm/services/phone_call_service
holds the EXACT-URL PIN), so an E2E environment can never obtain a call the
way production does. This command fabricates one instead. Its description
starts with ``[TEST]``, which is how ``e2e_cleanup`` finds it later and how
every other E2E-created row is recognised.

Lives in diagnostics rather than crm: it reads crm and job models together,
which is exactly the cross-domain operator work that sits above the domain
layer (the same reason ``e2e_cleanup`` is here).
"""

import json
import wave
from io import BytesIO
from uuid import UUID, uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from apps.core.environment import database_class
from apps.core.test_data import TEST_DATA_PREFIX, is_e2e_name
from apps.crm.models import PhoneCallRecord, PhoneCallRecording
from apps.crm.services.phone_call_service import normalize_phone, store_recording_bytes
from apps.job.models import Job

#: The caller's number and the office number the spec's call ran between.
CUSTOMER_NUMBER = "+6421555123"
OFFICE_NUMBER = "+6496365131"
#: The description is the marker the cleanup looks for.
CALL_DESCRIPTION = f"{TEST_DATA_PREFIX} CRM phone call job link"
RECORDING_FILENAME = "e2e-call.wav"
RECORDING_CONTENT_TYPE = "audio/wav"
CALL_DURATION_SECONDS = 67


def _silent_wav() -> bytes:
    """Build a tenth of a second of silence as a real WAV (1ch, 16-bit, 8 kHz).

    Generated rather than committed: a binary fixture in the repository would
    be a second thing to keep, and the spec only needs an ``<audio>`` element
    with something a browser will actually decode behind it.
    """
    buffer = BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 800)
    return buffer.getvalue()


class Command(BaseCommand):
    """Create one matched, recorded, job-less phone call against an E2E job's company.

    Emits exactly one JSON line on stdout — the E2E spec shells out to this
    command and parses the last non-empty line, so anything else written to
    stdout breaks a subprocess contract.
    """

    help = "Seed a recorded phone call against an E2E job's company (E2E environments only)"

    def add_arguments(self, parser: CommandParser) -> None:
        """Declare the single input the E2E subprocess contract fixes."""
        parser.add_argument(
            "--job",
            required=True,
            type=UUID,
            help="Job whose company the seeded call is matched to",
        )

    def handle(self, *args: object, **options: object) -> None:  # noqa: ARG002 -- BaseCommand signature
        """Refuse anything unsafe, then seed the call, recording and audio."""
        job_id = options["job"]
        if not isinstance(job_id, UUID):
            raise CommandError("--job must be a UUID")

        db_name = str(settings.DATABASES["default"]["NAME"])
        # The database name is the one signal a run cannot spoof (ADR 0048):
        # an environment variable saying "this is dev" is an input, not a
        # fact, so DEBUG is not consulted here.
        if database_class(db_name) == "prod":
            raise CommandError(
                f"Refusing to seed E2E phone data into production database: {db_name}."
            )

        job = Job.objects.select_related("company").filter(pk=job_id).first()
        if job is None:
            raise CommandError(f"No job with id {job_id}")
        if job.company is None:
            raise CommandError(
                f"Job {job.job_number} has no company: a phone call can only be linked to a "
                "job whose company matches the call's."
            )
        if not is_e2e_name(job.name):
            raise CommandError(
                f"Job {job.job_number} ({job.name!r}) is not E2E-named: refusing to hang "
                "fabricated provider data off a job the cleanup will not remove."
            )

        with transaction.atomic():
            call = self._create_call(job)
            recording = PhoneCallRecording.objects.create(
                call=call,
                provider_recording_id=f"{TEST_DATA_PREFIX} {uuid4()}",
                account_code=TEST_DATA_PREFIX,
            )
            store_recording_bytes(
                call=call,
                recording=recording,
                content=_silent_wav(),
                filename=RECORDING_FILENAME,
                content_type=RECORDING_CONTENT_TYPE,
            )

        self.stdout.write(
            json.dumps(
                {
                    "call_id": str(call.id),
                    "recording_id": str(recording.id),
                    "job_number": job.job_number,
                    "download_url": f"/api/crm/phone-call-recordings/{recording.id}/download/",
                },
                sort_keys=True,
            )
        )

    def _create_call(self, job: Job) -> PhoneCallRecord:
        """Create an inbound customer call, already matched to the job's company.

        Every identifier this seed invents — the account code, the provider
        call id, the description — starts with ``[TEST]``, so nothing written
        here can be mistaken for a value the provider sent. On a real row the
        account code is the provider's customer account number, so a
        plausible-looking one is exactly what it must not hold.

        The classification columns are set directly instead of running
        PhoneMatcher: the matcher reads the phone book and the configured
        endpoints, neither of which an E2E environment carries, so a matched
        call is a precondition of the spec rather than something to discover.
        The job link is deliberately left NULL — making it is what the spec
        drives through the UI.
        """
        now = timezone.now()
        call_uid = uuid4()
        local_date = timezone.localdate(now)
        local_time = timezone.localtime(now).time()
        return PhoneCallRecord.objects.create(
            provider_call_id=f"{TEST_DATA_PREFIX} {call_uid}",
            account_code=TEST_DATA_PREFIX,
            call_datetime=now,
            call_date=local_date,
            call_time=local_time,
            call_type="Inbound",
            status="Answered",
            description=CALL_DESCRIPTION,
            origin=CUSTOMER_NUMBER,
            destination=OFFICE_NUMBER,
            normalized_origin=normalize_phone(CUSTOMER_NUMBER),
            normalized_destination=normalize_phone(OFFICE_NUMBER),
            direction=PhoneCallRecord.Direction.INBOUND,
            our_number=normalize_phone(OFFICE_NUMBER),
            external_number=normalize_phone(CUSTOMER_NUMBER),
            duration_seconds=CALL_DURATION_SECONDS,
            company=job.company,
            raw_json={
                "id": str(call_uid),
                "calldate": local_date.isoformat(),
                "calltime": local_time.isoformat(timespec="seconds"),
                "origin": CUSTOMER_NUMBER,
                "destination": OFFICE_NUMBER,
            },
        )
