"""AI APIs: provider administration and the NotebookLM training menu.

Served under ``/api/ai/``, matching the app the model lives in. v1 served it
from an app called ``workflow`` that v2 does not have, and no external party
holds the URL, so there is nothing to preserve.
"""

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.ai.enums import AIProviderTypes, NotebookLmRestriction
from apps.ai.models import AIProvider, NotebookLmLink
from apps.ai.services.provider_configuration import (
    ProviderCreate,
    ProviderPatch,
    create_provider,
    set_default_provider,
    update_provider,
    verify_provider,
)
from apps.core.auth import CookieJWTAuth, StaffPermissions, SuperuserCookieJWTAuth

router = Router(tags=["ai"])
auth = CookieJWTAuth()


class NotebookLmLinkOut(Schema):
    """One entry in the training menu."""

    id: int
    name: str
    url: str
    enabled: bool
    restriction: str
    order: int


@router.get(
    "/ai/notebook-lm-links/menu/",
    auth=auth,
    operation_id="notebook_lm_links_menu_list",
    response=list[NotebookLmLinkOut],
    summary="Training-menu links visible to the current staff member",
    tags=["ai"],
)
def notebook_lm_links_menu_list(request: HttpRequest) -> list[NotebookLmLink]:
    """Return the enabled links this staff member may see.

    Filtered server-side, not in the navbar. Sending every link and letting the
    client hide some would put the restricted ones in the response body of every
    page load, where anyone can read them — the filter would be decoration.

    It is still a UX filter rather than an access boundary: NotebookLM itself
    enforces access through Drive ACLs, so a leaked URL is not a way in. That is
    the reason this can be a plain queryset filter and not an authorisation
    check with its own tests.
    """
    user = request.user
    is_superuser = isinstance(user, StaffPermissions) and user.is_superuser
    links = NotebookLmLink.objects.filter(enabled=True)
    if not is_superuser:
        links = links.exclude(restriction=NotebookLmRestriction.SUPERUSER)
    return list(links)


provider_router = Router(tags=["ai-providers"], auth=SuperuserCookieJWTAuth())


class ProviderOut(Schema):
    """Safe catalogue metadata; a stored secret is represented by presence only."""

    id: int
    name: str
    provider_type: AIProviderTypes
    model_name: str | None
    default: bool
    has_api_key: bool

    @staticmethod
    def resolve_has_api_key(provider: AIProvider) -> bool:
        """Report presence without returning the key, even to the administrator."""
        return provider.api_key is not None


class ProviderTestOut(Schema):
    """A successful live test names the actual gateway model."""

    model: str


@provider_router.get("/", response=list[ProviderOut], operation_id="ai_providers_list")
def list_providers(request: HttpRequest) -> list[AIProvider]:
    """Show every configured or incomplete row without creating defaults."""
    return list(AIProvider.objects.order_by("name", "pk"))


@provider_router.post("/", response={201: ProviderOut}, operation_id="ai_providers_create")
def add_provider(request: HttpRequest, payload: ProviderCreate) -> tuple[int, AIProvider]:
    """Create through the shared admin/bootstrap validation service."""
    return 201, create_provider(payload)


@provider_router.patch(
    "/{provider_id}/", response=ProviderOut, operation_id="ai_providers_partial_update"
)
def edit_provider(request: HttpRequest, provider_id: int, payload: ProviderPatch) -> AIProvider:
    """Apply only the administrator's edited fields."""
    return update_provider(provider_id, payload)


@provider_router.delete(
    "/{provider_id}/", response={204: None}, operation_id="ai_providers_destroy"
)
def delete_provider(request: HttpRequest, provider_id: int) -> tuple[int, None]:
    """Delete the chosen row without guessing a replacement default."""
    get_object_or_404(AIProvider, pk=provider_id).delete()
    return 204, None


@provider_router.post(
    "/{provider_id}/set-default/", response=ProviderOut, operation_id="ai_providers_set_default"
)
def choose_default(request: HttpRequest, provider_id: int) -> AIProvider:
    """Select the fallback used by callers that do not supply a provider."""
    return set_default_provider(provider_id)


@provider_router.post(
    "/{provider_id}/test/", response=ProviderTestOut, operation_id="ai_providers_test"
)
def test_provider(request: HttpRequest, provider_id: int) -> ProviderTestOut:
    """Perform a small billable request only when explicitly requested."""
    return ProviderTestOut(model=verify_provider(get_object_or_404(AIProvider, pk=provider_id)))
