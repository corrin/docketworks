import uuid
from typing import ClassVar

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class PersonCleanupMigrationTests(TransactionTestCase):
    """The cleanup removes only rows with no remaining business references."""

    migrate_from: ClassVar[tuple[tuple[str, str], ...]] = (
        ("company", "0006_alter_companypersonlink_options_and_more"),
        ("crm", "0006_remove_phonecallrecord_contact_and_more"),
        ("job", "0006_rename_job_event_people_company_terms"),
    )
    migrate_to: ClassVar[tuple[tuple[str, str], ...]] = (
        ("company", "0007_remove_xero_person_identity"),
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

    def test_removes_unreferenced_person_and_preserves_every_reference_kind(
        self,
    ) -> None:
        Company = self.old_apps.get_model("company", "Company")
        Person = self.old_apps.get_model("company", "Person")
        CompanyPersonLink = self.old_apps.get_model("company", "CompanyPersonLink")
        ContactMethod = self.old_apps.get_model("company", "ContactMethod")
        Job = self.old_apps.get_model("job", "Job")
        CostSet = self.old_apps.get_model("job", "CostSet")
        PhoneCallRecord = self.old_apps.get_model("crm", "PhoneCallRecord")
        XeroPayItem = self.old_apps.get_model("workflow", "XeroPayItem")

        company = Company.objects.create(name="Acme", xero_last_modified=timezone.now())
        unreferenced = Person.objects.create(name="Unreferenced")
        linked = Person.objects.create(name="Linked")
        method_owner = Person.objects.create(name="Method Owner")
        job_person = Person.objects.create(name="Job Person")
        call_person = Person.objects.create(name="Call Person")
        CompanyPersonLink.objects.create(company=company, person=linked)
        ContactMethod.objects.create(
            person=method_owner,
            method_type="email",
            value="method@example.com",
            normalized_value="method@example.com",
        )
        pay_item, _created = XeroPayItem.objects.get_or_create(
            name="Ordinary Time",
            uses_leave_api=False,
            defaults={"multiplier": "1.00"},
        )
        estimate_id = uuid.uuid4()
        quote_id = uuid.uuid4()
        actual_id = uuid.uuid4()
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET CONSTRAINTS ALL DEFERRED")
            job = Job.objects.create(
                company=company,
                person=job_person,
                name="Migration Job",
                job_number=998101,
                default_xero_pay_item=pay_item,
                latest_estimate_id=estimate_id,
                latest_quote_id=quote_id,
                latest_actual_id=actual_id,
            )
            CostSet.objects.create(id=estimate_id, job=job, kind="estimate", rev=1)
            CostSet.objects.create(id=quote_id, job=job, kind="quote", rev=1)
            CostSet.objects.create(id=actual_id, job=job, kind="actual", rev=1)
        now = timezone.now()
        PhoneCallRecord.objects.create(
            provider_call_id="person-cleanup-migration",
            account_code="account",
            call_datetime=now,
            call_date=timezone.localdate(),
            call_time=now.time(),
            person=call_person,
            raw_json={},
        )

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        new_apps = self.executor.loader.project_state(self.migrate_to).apps
        Person = new_apps.get_model("company", "Person")
        CompanyPersonLink = new_apps.get_model("company", "CompanyPersonLink")

        self.assertFalse(Person.objects.filter(id=unreferenced.id).exists())
        for person in (linked, method_owner, job_person, call_person):
            self.assertTrue(Person.objects.filter(id=person.id).exists())
        self.assertNotIn(
            "xero_name",
            {field.name for field in CompanyPersonLink._meta.get_fields()},
        )
