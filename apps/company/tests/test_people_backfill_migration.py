import uuid
from typing import ClassVar

from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class PeopleBackfillMigrationTests(TransactionTestCase):
    migrate_from: ClassVar[tuple[tuple[str, str], ...]] = (
        ("company", "0004_person_link_structure"),
        ("job", "0004_job_person_alter_job_contact"),
        ("crm", "0005_phonecallrecord_person_alter_phonecallrecord_contact"),
    )
    migrate_to: ClassVar[tuple[tuple[str, str], ...]] = (
        ("company", "0005_backfill_person"),
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

    def test_backfill_and_reverse_restore_legacy_contact_ownership(self) -> None:
        Company = self.old_apps.get_model("company", "Company")
        CompanyPersonLink = self.old_apps.get_model("company", "CompanyPersonLink")
        ContactMethod = self.old_apps.get_model("company", "ContactMethod")
        Job = self.old_apps.get_model("job", "Job")
        CostSet = self.old_apps.get_model("job", "CostSet")
        PhoneCallRecord = self.old_apps.get_model("crm", "PhoneCallRecord")
        XeroPayItem = self.old_apps.get_model("workflow", "XeroPayItem")

        company = Company.objects.create(
            name="Acme",
            xero_last_modified=timezone.now(),
        )
        link = CompanyPersonLink.objects.create(
            company=company,
            name="Jane Smith",
            email="jane@example.com",
            is_primary=True,
        )
        method = ContactMethod.objects.create(
            contact=link,
            method_type="phone",
            value="021 123 456",
            normalized_value="+6421123456",
            is_primary=True,
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
                contact=link,
                name="Test job",
                job_number=991001,
                default_xero_pay_item=pay_item,
                latest_estimate_id=estimate_id,
                latest_quote_id=quote_id,
                latest_actual_id=actual_id,
            )
            CostSet.objects.create(id=estimate_id, job=job, kind="estimate", rev=1)
            CostSet.objects.create(id=quote_id, job=job, kind="quote", rev=1)
            CostSet.objects.create(id=actual_id, job=job, kind="actual", rev=1)
        now = timezone.now()
        call = PhoneCallRecord.objects.create(
            provider_call_id="call-people-backfill",
            account_code="acct",
            call_datetime=now,
            call_date=timezone.localdate(),
            call_time=now.time(),
            company=company,
            contact=link,
            raw_json={},
        )

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_to)
        new_apps = self.executor.loader.project_state(self.migrate_to).apps
        Person = new_apps.get_model("company", "Person")
        CompanyPersonLink = new_apps.get_model("company", "CompanyPersonLink")
        ContactMethod = new_apps.get_model("company", "ContactMethod")
        Job = new_apps.get_model("job", "Job")
        PhoneCallRecord = new_apps.get_model("crm", "PhoneCallRecord")

        person = Person.objects.get(name="Jane Smith")
        link = CompanyPersonLink.objects.get(pk=link.pk)
        method = ContactMethod.objects.get(pk=method.pk)
        job = Job.objects.get(pk=job.pk)
        call = PhoneCallRecord.objects.get(pk=call.pk)

        self.assertEqual(link.person_id, person.pk)
        self.assertEqual(link.xero_name, "Jane Smith")
        self.assertEqual(person.email, "jane@example.com")
        self.assertEqual(method.person_id, person.pk)
        self.assertIsNone(method.contact_id)
        self.assertEqual(job.person_id, person.pk)
        self.assertEqual(call.person_id, person.pk)

        self.executor.loader.build_graph()
        self.executor.migrate(self.migrate_from)
        reversed_apps = self.executor.loader.project_state(self.migrate_from).apps
        Person = reversed_apps.get_model("company", "Person")
        CompanyPersonLink = reversed_apps.get_model("company", "CompanyPersonLink")
        ContactMethod = reversed_apps.get_model("company", "ContactMethod")
        Job = reversed_apps.get_model("job", "Job")
        PhoneCallRecord = reversed_apps.get_model("crm", "PhoneCallRecord")

        link = CompanyPersonLink.objects.get(pk=link.pk)
        method = ContactMethod.objects.get(pk=method.pk)
        job = Job.objects.get(pk=job.pk)
        call = PhoneCallRecord.objects.get(pk=call.pk)

        self.assertIsNone(link.person_id)
        self.assertIsNone(link.xero_name)
        self.assertEqual(link.name, "Jane Smith")
        self.assertEqual(method.contact_id, link.pk)
        self.assertIsNone(method.person_id)
        self.assertEqual(job.contact_id, link.pk)
        self.assertIsNone(job.person_id)
        self.assertEqual(call.contact_id, link.pk)
        self.assertIsNone(call.person_id)
        self.assertEqual(Person.objects.count(), 0)
