"""Shared factories for the crm test modules."""

from datetime import datetime

from django.test import Client
from django.utils import timezone
from ninja_jwt.tokens import RefreshToken

from apps.accounts.models import Staff
from apps.company.models import Company, CompanyPersonLink, Person
from apps.crm.models import PhoneCallRecord, PhoneCallRecording
from apps.job.models import Job

PASSWORD = "testpass-123!"


def cookie_client(staff: Staff) -> Client:
    """A django test Client authenticated via the HttpOnly JWT cookie."""
    client = Client()
    refresh = RefreshToken.for_user(staff)
    client.cookies["access_token"] = str(refresh.access_token)
    return client


def make_office_staff(email: str = "crm-office@example.com") -> Staff:
    return Staff.objects.create_user(office_email=email, password=PASSWORD, is_office_staff=True)


def make_superuser(email: str = "crm-admin@example.com") -> Staff:
    return Staff.objects.create_user(
        office_email=email,
        password=PASSWORD,
        is_office_staff=True,
        is_superuser=True,
    )


def make_company(name: str = "Acme Ltd") -> Company:
    return Company.objects.create(name=name, xero_last_modified=timezone.now())


def link_person(company: Company, name: str) -> CompanyPersonLink:
    person = Person.objects.create(name=name)
    return CompanyPersonLink.objects.create(company=company, person=person)


def make_job(company: Company, name: str, staff: Staff) -> Job:
    """Create a Job through the real save path."""
    job = Job(company=company, name=name)
    job.save(staff=staff)
    return job


def make_call(  # noqa: PLR0913 -- a factory: every field is an axis a test varies
    provider_id: str,
    *,
    company: Company | None = None,
    origin: str = "+6421555123",
    destination: str = "+6496365131",
    call_datetime: datetime | None = None,
    description: str | None = None,
) -> PhoneCallRecord:
    when = call_datetime or timezone.now()
    return PhoneCallRecord.objects.create(
        provider_call_id=f"account:{provider_id}",
        account_code="account",
        description=description,
        call_datetime=when,
        call_date=timezone.localdate(when),
        call_time=when.time(),
        origin=origin,
        destination=destination,
        company=company,
        raw_json={
            "id": provider_id,
            "calldate": timezone.localdate(when).isoformat(),
            "calltime": when.time().isoformat(timespec="seconds"),
        },
    )


def make_recording(
    call: PhoneCallRecord,
    provider_recording_id: str,
    *,
    storage_path: str | None,
    provider_deleted_at: datetime | None = None,
) -> PhoneCallRecording:
    return PhoneCallRecording.objects.create(
        call=call,
        provider_recording_id=provider_recording_id,
        account_code="account",
        storage_path=storage_path,
        archived_at=timezone.now(),
        provider_deleted_at=provider_deleted_at,
    )
