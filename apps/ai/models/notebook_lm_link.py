"""NotebookLM link model."""

from typing import ClassVar

from django.db import models
from django.utils.translation import gettext_lazy

from apps.ai.enums import NotebookLmRestriction


class NotebookLmLink(models.Model):
    """A NotebookLM notebook link shown in the app's training menu.

    Per-instance and admin-managed: each client configures their own rows.
    `restriction` decides which staff see the link in the navbar; it is a UX
    filter, not an access boundary (NotebookLM access is enforced by Drive ACLs).
    """

    name = models.CharField(max_length=100, help_text=gettext_lazy("Menu item name"))
    url = models.URLField(help_text=gettext_lazy("NotebookLM notebook URL"))
    enabled = models.BooleanField(
        default=True, help_text=gettext_lazy("Show this link in the training menu")
    )
    restriction = models.CharField(
        max_length=20,
        choices=NotebookLmRestriction,
        default=NotebookLmRestriction.NONE,
        help_text=gettext_lazy("Who may see this link in the menu"),
    )
    order = models.IntegerField(default=0, help_text=gettext_lazy("Menu display order"))

    class Meta:
        db_table = "workflow_notebooklmlink"  # v1 home was the workflow app
        ordering: ClassVar[list[str]] = ["order", "name"]
        verbose_name = gettext_lazy("NotebookLM Link")
        verbose_name_plural = gettext_lazy("NotebookLM Links")

    def __str__(self) -> str:
        return self.name
