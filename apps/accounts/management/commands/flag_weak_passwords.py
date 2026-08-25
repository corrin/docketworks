"""Force a password reset for every user at next login."""

from django.core.management.base import BaseCommand

from apps.accounts.models import Staff


class Command(BaseCommand):
    """Mark every Staff row as requiring a password reset on next login."""

    help = "Marks all users to require password reset on next login"

    def handle(self, *_args: object, **_options: object) -> None:
        """Set ``password_needs_reset`` on every user, one save per row.

        A bulk ``.update()`` would be one statement, but it bypasses
        ``Staff.save()`` and simple-history, leaving no audit trail for a
        security-relevant flag flip; per-row saves keep the history rows.
        """
        count = 0
        for user in Staff.objects.all():
            user.password_needs_reset = True
            user.save(update_fields=["password_needs_reset", "updated_at"])
            count += 1
            self.stdout.write(
                f"User {user.office_email or user.payroll_email} marked for password reset"
            )

        self.stdout.write(self.style.SUCCESS(f"{count} users marked to reset their passwords"))
