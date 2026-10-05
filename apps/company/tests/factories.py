"""Company test data without importing pytest fixture wiring."""

from django.utils import timezone

from apps.company.models import Company

#: The organisation a factory-made linked company belongs to when the test does
#: not care which. A contact id is never stored without one.
FACTORY_TENANT = "factory-tenant"


def make_company(name: str, **kwargs: object) -> Company:
    """Create a Company with the only field the model truly requires."""
    defaults: dict[str, object] = {"xero_last_modified": timezone.now()}
    if kwargs.get("xero_contact_id") is not None:
        defaults["xero_tenant_id"] = FACTORY_TENANT
    defaults.update(kwargs)
    return Company.objects.create(name=name, **defaults)
