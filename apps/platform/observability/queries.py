"""Read-only questions the recorded vendor calls can answer."""

from datetime import timedelta

from django.utils import timezone

from apps.platform.observability.models import VendorCall


def latest_day_remaining(*, vendor: VendorCall.Vendor, not_older_than: timedelta) -> int | None:
    """Return the freshest day-quota reading the vendor gave inside the window.

    ``None`` means no such reading exists — no call has been made yet, the
    window has aged out, or the responses carried no quota header. It is the
    vendor's absence rather than an authored union, so the caller's neutral
    behaviour is to treat the quota as unknown rather than exhausted.
    """
    return (
        VendorCall.objects.filter(
            vendor=vendor,
            day_remaining__isnull=False,
            occurred_at__gte=timezone.now() - not_older_than,
        )
        .values_list("day_remaining", flat=True)
        .first()
    )
