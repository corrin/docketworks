import datetime

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = (
        "Fixes circular migration dependencies by manually inserting migration records"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would be done without making any changes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Skip confirmation and execute immediately",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        force = options["force"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("Running in dry-run mode - no changes will be made")
            )

        # Check if the migrations are already applied
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT * FROM django_migrations
                WHERE app='accounts' AND name='0001_initial'
                """)
            if cursor.fetchone():
                self.stdout.write(
                    self.style.SUCCESS(
                        "accounts.0001_initial migration is already applied"
                    )
                )
                return

            # Get the date of admin.0001_initial migration
            cursor.execute("""
                SELECT applied FROM django_migrations
                WHERE app='auth' AND name='0001_initial'
                """)
            result = cursor.fetchone()
            if not result:
                self.stdout.write(
                    self.style.ERROR(
                        "admin.0001_initial migration not found in the database"
                    )
                )
                return

            admin_applied_date = result[0]
            # Calculate a date 1 minute before the admin migration
            accounts_applied_date = admin_applied_date - datetime.timedelta(minutes=1)

            # Show the plan
            self.stdout.write(
                self.style.WARNING(
                    f"Found admin.0001_initial applied at: {admin_applied_date}"
                )
            )
            self.stdout.write(
                self.style.WARNING(
                    f"Will insert accounts migrations with date: "
                    f"{accounts_applied_date}"
                )
            )

            # Ask for confirmation unless force is used
            if not force and not dry_run:
                confirm = input(
                    "Are you sure you want to insert these migration records? [y/N]: "
                )
                if confirm.lower() != "y":
                    self.stdout.write(self.style.WARNING("Operation cancelled"))
                    return

            # Insert the migration records
            accounts_0002_date = accounts_applied_date + datetime.timedelta(seconds=1)
            if not dry_run:
                try:
                    cursor.execute(f"""
                        INSERT INTO django_migrations (app, name, applied)
                        VALUES ('accounts', '0001_initial', '{accounts_applied_date}')
                        """)
                    cursor.execute(f"""
                        INSERT INTO django_migrations (app, name, applied)
                        VALUES ('accounts', '0002_initial', '{accounts_0002_date}')
                        """)
                    self.stdout.write(
                        self.style.SUCCESS(
                            "Successfully inserted migration records in "
                            "django_migrations table"
                        )
                    )
                    self.stdout.write(
                        self.style.SUCCESS(
                            'You can now run "python manage.py migrate" safely'
                        )
                    )
                except Exception as e:
                    self.stdout.write(
                        self.style.ERROR(f"Error inserting migration records: {str(e)}")
                    )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        "In non-dry-run mode, would insert these records:"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"accounts.0001_initial with date {accounts_applied_date}"
                    )
                )
                self.stdout.write(
                    self.style.WARNING(
                        f"accounts.0002_initial with date {accounts_0002_date}"
                    )
                )
