from django.conf import settings
from django.test import SimpleTestCase


class ScrubDbAliasTests(SimpleTestCase):
    def test_scrub_alias_exists(self):
        self.assertIn("scrub", settings.DATABASES)

    def test_scrub_alias_shape_matches_default(self):
        default = settings.DATABASES["default"]
        scrub = settings.DATABASES["scrub"]
        self.assertEqual(scrub["ENGINE"], default["ENGINE"])
        self.assertEqual(scrub["USER"], default["USER"])
        self.assertEqual(scrub["PASSWORD"], default["PASSWORD"])
        self.assertEqual(scrub["HOST"], default["HOST"])
        self.assertEqual(scrub["PORT"], default["PORT"])

    def test_scrub_name_hard_fails_if_not_suffixed(self):
        # Guard against pointing scrub alias at prod by misconfiguration.
        self.assertTrue(
            settings.DATABASES["scrub"]["NAME"].endswith("_scrub"),
            "SCRUB_DB_NAME must end in '_scrub' to prevent scrubbing prod",
        )
