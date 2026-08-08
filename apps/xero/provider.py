"""Xero accounting provider — delegates to apps/xero auth and contact push."""

import logging
from typing import TYPE_CHECKING
from uuid import UUID

from xero_python.accounting import AccountingApi

from apps.accounting.types import ContactResult, DocumentTheme
from apps.core.errors import persist_app_error
from apps.xero.active_app import NoActiveXeroAppError, get_active_app, wipe_tokens_and_quota
from apps.xero.auth import TokenPayload, get_api_client, get_tenant_id, get_valid_token
from apps.xero.contacts import create_company_contact_in_xero, sync_company_to_xero

if TYPE_CHECKING:
    from apps.company.models import Company

logger = logging.getLogger(__name__)


class XeroAccountingProvider:
    """Xero implementation of the AccountingProvider protocol."""

    @staticmethod
    def _get_api() -> tuple[AccountingApi, str]:
        return AccountingApi(get_api_client()), get_tenant_id()

    # --- Auth ---

    def get_valid_token(self) -> TokenPayload | None:
        """See AccountingProvider.get_valid_token."""
        return get_valid_token()

    def disconnect(self) -> None:
        """Wipe the active app's stored tokens; a no-op when nothing is connected."""
        try:
            active = get_active_app()
        except NoActiveXeroAppError:
            return
        wipe_tokens_and_quota(active)

    # --- Contacts ---

    def create_contact(self, company: "Company") -> ContactResult:
        """See AccountingProvider.create_contact."""
        try:
            xero_contact_id = create_company_contact_in_xero(company)
        except Exception as exc:  # noqa: BLE001 -- persisted, then converted to the result type callers require
            persist_app_error(exc)
            return ContactResult(success=False, error=str(exc))
        return ContactResult(success=True, external_id=xero_contact_id, name=company.name)

    def update_contact(self, company: "Company") -> ContactResult:
        """See AccountingProvider.update_contact."""
        try:
            sync_company_to_xero(company)
        except Exception as exc:  # noqa: BLE001 -- persisted, then converted to the result type callers require
            persist_app_error(exc)
            return ContactResult(success=False, error=str(exc))
        return ContactResult(success=True, external_id=company.xero_contact_id, name=company.name)

    def search_contact_by_name(self, name: str) -> ContactResult | None:
        """See AccountingProvider.search_contact_by_name."""
        api, tenant_id = self._get_api()
        response = api.get_contacts(tenant_id, where=f'Name=="{name}"')
        contacts = response.contacts or []
        if not contacts:
            return None
        return ContactResult(
            success=True,
            external_id=str(contacts[0].contact_id),
            name=contacts[0].name,
        )

    # --- Documents ---

    def list_document_themes(self) -> list[DocumentTheme]:
        """See AccountingProvider.list_document_themes."""
        try:
            api, tenant_id = self._get_api()
            response = api.get_branding_themes(tenant_id)
            ranked_themes: list[tuple[int, DocumentTheme]] = []

            for theme in response.branding_themes:
                # ValueError, not TypeError: these guard malformed API data
                # from Xero, not a caller passing the wrong type.
                if not isinstance(theme.branding_theme_id, str):
                    raise ValueError(  # noqa: TRY004
                        "Xero branding theme is missing its identifier"
                    )
                if not isinstance(theme.name, str) or not theme.name:
                    raise ValueError("Xero branding theme is missing its name")
                if not isinstance(theme.sort_order, int):
                    raise ValueError(  # noqa: TRY004
                        f"Xero branding theme {theme.name} is missing its sort order"
                    )

                external_id = str(UUID(theme.branding_theme_id))
                ranked_themes.append(
                    (
                        theme.sort_order,
                        DocumentTheme(
                            external_id=external_id,
                            name=theme.name,
                            is_default=theme.sort_order == 0,
                        ),
                    )
                )
        except Exception as exc:
            persist_app_error(exc)
            raise
        return [theme for _sort_order, theme in sorted(ranked_themes)]
