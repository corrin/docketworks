import os
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase

from docketworks.settings import _validate_sha, read_build_id

VALID_SHA = "0123456789abcdef0123456789abcdef01234567"


class ValidateShaTests(SimpleTestCase):
    def test_accepts_40_char_hex_sha(self) -> None:
        self.assertEqual(_validate_sha(VALID_SHA, "test"), VALID_SHA)

    def test_strips_surrounding_whitespace(self) -> None:
        self.assertEqual(_validate_sha(f"  {VALID_SHA}\n", "test"), VALID_SHA)

    def test_rejects_empty(self) -> None:
        with self.assertRaises(ImproperlyConfigured):
            _validate_sha("", "test")

    def test_rejects_short_hash(self) -> None:
        with self.assertRaises(ImproperlyConfigured):
            _validate_sha("0123abc", "test")

    def test_rejects_non_hex(self) -> None:
        with self.assertRaises(ImproperlyConfigured):
            _validate_sha("z" * 40, "test")


class ReadBuildIdTests(SimpleTestCase):
    def test_returns_validated_env_sha(self) -> None:
        with mock.patch.dict(os.environ, {"DOCKETWORKS_BUILD_SHA": VALID_SHA}):
            self.assertEqual(read_build_id(), VALID_SHA)

    def test_rejects_invalid_env_sha(self) -> None:
        with mock.patch.dict(os.environ, {"DOCKETWORKS_BUILD_SHA": "not-a-sha"}):
            with self.assertRaises(ImproperlyConfigured):
                read_build_id()
