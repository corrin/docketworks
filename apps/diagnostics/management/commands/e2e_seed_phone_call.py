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
from uuid import UUID, uuid4

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from apps.core.environment import ProductionDatabaseError, assert_not_production_database
from apps.core.test_data import TEST_DATA_PREFIX, is_e2e_name, silent_wav
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
#: Long enough that the player's stored length reads as something (0:03), short
#: enough that the spec's wire guard never notices it.
RECORDING_SECONDS = 3
CALL_DURATION_SECONDS = 67


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

    def handle(self, *_args: object, **options: object) -> None:
        """Refuse anything unsafe, then seed the call, recording and audio."""
        job_id = options["job"]
        if not isinstance(job_id, UUID):
            raise CommandError("--job must be a UUID")

        try:
            assert_not_production_database(
                "this command fabricates a phone call, its recording and its audio."
            )
        except ProductionDatabaseError as exc:
            raise CommandError(str(exc)) from exc

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

        # The recording id is minted before the call because it belongs in the
        # call's raw_json too: download_recording reads raw["RecordingId"].
        provider_recording_id = f"{TEST_DATA_PREFIX} {uuid4()}"

        with transaction.atomic():
            call = self._create_call(job, provider_recording_id=provider_recording_id)
            recording = PhoneCallRecording.objects.create(
                call=call,
                provider_recording_id=provider_recording_id,
                account_code=TEST_DATA_PREFIX,
            )
            # Fable: the file is written inside the transaction, so a commit
            # failure strands a file no row names. Chosen because nothing
            # follows the write but the commit itself, whereas writing after
            # it would leave a row whose file never arrives — and that row is
            # what the spec plays.
            store_recording_bytes(
                call=call,
                recording=recording,
                content=silent_wav(RECORDING_SECONDS),
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

    def _create_call(self, job: Job, *, provider_recording_id: str) -> PhoneCallRecord:
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
            # Every key the provider sends, because readers index rather
            # than probe: download_recording reads raw["RecordingId"] and
            # _filename_from_response reads raw["calldate"]/["calltime"]. A
            # subset here would be a KeyError in production code.
            raw_json={
                "id": str(call_uid),
                "calldate": local_date.isoformat(),
                "calltime": local_time.isoformat(timespec="seconds"),
                "origin": CUSTOMER_NUMBER,
                "destination": OFFICE_NUMBER,
                "seconds": str(CALL_DURATION_SECONDS),
                "charge": "0.0000",
                "type": "Inbound",
                "status": "Answered",
                "description": CALL_DESCRIPTION,
                "RecordingId": provider_recording_id,
            },
        )
