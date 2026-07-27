from django.db import models

from apps.workflow.enums import NotebookLmRestriction


class NotebookLmLink(models.Model):
    """A NotebookLM notebook link shown in the app's training menu.

    Per-instance and admin-managed: each client configures their own rows.
    `restriction` decides which staff see the link in the navbar; it is a UX
    filter, not an access boundary (NotebookLM access is enforced by Drive ACLs).
    """

    name = models.CharField(max_length=100, help_text="Menu item name")
    url = models.URLField(help_text="NotebookLM notebook URL")
    enabled = models.BooleanField(
        default=True, help_text="Show this link in the training menu"
    )
    restriction = models.CharField(
        max_length=20,
        choices=NotebookLmRestriction,
        default=NotebookLmRestriction.NONE,
        help_text="Who may see this link in the menu",
    )
    order = models.IntegerField(default=0, help_text="Menu display order")

    def __str__(self) -> str:
        return self.name

    class Meta:
        ordering = ["order", "name"]
        verbose_name = "NotebookLM Link"
        verbose_name_plural = "NotebookLM Links"
