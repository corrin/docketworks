from typing import Any

from xero_python.api_client import ApiClient

class Phone:
    phone_type: str | None
    phone_number: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class Address:
    address_type: str | None
    attention_to: str | None
    address_line1: str | None
    def __init__(self, **kwargs: Any) -> None: ...

class Contact:
    contact_id: str | None
    name: str | None
    email_address: str | None
    phones: list[Phone] | None
    addresses: list[Address] | None
    is_customer: bool | None
    def __init__(self, **kwargs: Any) -> None: ...
    def to_dict(self) -> dict[str, Any]: ...

class Contacts:
    contacts: list[Contact] | None
    def __init__(self, contacts: list[Contact] | None = None, **kwargs: Any) -> None: ...

class BrandingTheme:
    branding_theme_id: str | None
    name: str | None
    sort_order: int | None
    def __init__(self, **kwargs: Any) -> None: ...

class BrandingThemes:
    branding_themes: list[BrandingTheme]
    def __init__(self, **kwargs: Any) -> None: ...

class AccountingApi:
    def __init__(self, api_client: ApiClient) -> None: ...
    def create_contacts(
        self, xero_tenant_id: str, contacts: Any = ..., **kwargs: Any
    ) -> Contacts: ...
    def update_contact(
        self, xero_tenant_id: str, contact_id: Any = ..., contacts: Any = ..., **kwargs: Any
    ) -> Contacts: ...
    def get_contacts(self, xero_tenant_id: str, **kwargs: Any) -> Contacts: ...
    def get_branding_themes(self, xero_tenant_id: str, **kwargs: Any) -> BrandingThemes: ...
