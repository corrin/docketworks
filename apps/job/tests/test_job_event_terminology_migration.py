from typing import ClassVar

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class JobEventTerminologyMigrationTests(TransactionTestCase):
    migrate_from: ClassVar[tuple[tuple[str, str], ...]] = (
        ("job", "0005_remove_job_contact_alter_job_person"),
    )
    migrate_to: ClassVar[tuple[tuple[str, str], ...]] = (
        ("job", "0006_rename_job_event_people_company_terms"),
    )

    def setUp(self) -> None:
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(self.migrate_from)
        self.old_apps = self.executor.loader.project_state(self.migrate_from).apps

    def tearDown(self) -> None:
        self.executor.loader.build_graph()
        self.executor.migrate(self.executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_forward_and_reverse_rename_event_types_and_detail_labels(self) -> None:
        Staff = self.old_apps.get_model("accounts", "Staff")
        JobEvent = self.old_apps.get_model("job", "JobEvent")
        staff = Staff.objects.create(
            email="migration-staff@example.test",
            password="not-used",
            first_name="Migration",
            last_name="Staff",
            wage_rate=0,
            base_wage_rate=0,
        )
        company_event = JobEvent.objects.create(
            staff=staff,
            event_type="client_changed",
            detail={
                "field_name": "Client",
                "old_value": "Old Co",
                "new_value": "New Co",
            },
        )
        person_event = JobEvent.objects.create(
            staff=staff,
            event_type="contact_changed",
            detail={
                "changes": [
                    {
                        "field_name": "Contact",
                        "old_value": "Old Person",
                        "new_value": "New Person",
                    }
                ]
            },
        )

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        new_apps = self.executor.loader.project_state(self.migrate_to).apps
        JobEvent = new_apps.get_model("job", "JobEvent")

        company_event = JobEvent.objects.get(pk=company_event.pk)
        person_event = JobEvent.objects.get(pk=person_event.pk)
        self.assertEqual(company_event.event_type, "company_changed")
        self.assertEqual(company_event.detail["field_name"], "Company")
        self.assertEqual(person_event.event_type, "person_changed")
        self.assertEqual(person_event.detail["changes"][0]["field_name"], "Person")

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_from)
        reversed_apps = self.executor.loader.project_state(self.migrate_from).apps
        JobEvent = reversed_apps.get_model("job", "JobEvent")

        company_event = JobEvent.objects.get(pk=company_event.pk)
        person_event = JobEvent.objects.get(pk=person_event.pk)
        self.assertEqual(company_event.event_type, "client_changed")
        self.assertEqual(company_event.detail["field_name"], "Client")
        self.assertEqual(person_event.event_type, "contact_changed")
        self.assertEqual(person_event.detail["changes"][0]["field_name"], "Contact")
