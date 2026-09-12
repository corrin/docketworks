"""Company test data without importing pytest fixture wiring."""

from django.utils import timezone

from apps.company.models import Company


def make_company(name: str, **kwargs: object) -> Company:
    """Create a Company with the only field the model truly requires."""
    defaults: dict[str, object] = {"xero_last_modified": timezone.now()}
    defaults.update(kwargs)
    return Company.objects.create(name=name, **defaults)
