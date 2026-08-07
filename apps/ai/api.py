"""AI router. Currently the NotebookLM training menu the navbar reads.

Served under ``/api/ai/``, matching the app the model lives in. v1 served it
from an app called ``workflow`` that v2 does not have, and no external party
holds the URL, so there is nothing to preserve.
"""

from django.http import HttpRequest
from ninja import Router, Schema

from apps.ai.enums import NotebookLmRestriction
from apps.ai.models import NotebookLmLink
from apps.core.auth import CookieJWTAuth, StaffPermissions

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
