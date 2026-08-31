"""Force a password change for EVERY user — including live sessions.

Despite the historical name, this flags every Staff row, not just weak
passwords. Since the auth-layer gate landed (apps/core/auth.py), the flag
confines every EXISTING session — superusers included — to the change screen
immediately, not merely at next login. Run it only when a company-wide
credential rotation is the intent.
"""

from django.core.management.base import BaseCommand

from apps.accounts.models import Staff


class Command(BaseCommand):
    """Mark every Staff row as requiring a password change."""

    help = (
        "Flags EVERY user (admins included) to change their password; live "
        "sessions are locked to the change screen immediately."
    )

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
