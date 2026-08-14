"""Minimal typing stub for the google-auth surface scripts/gdocs uses.

google-auth ships py.typed but ``service_account.Credentials``'s constructors
and ``with_subject`` are untyped defs, which strict mypy rejects at every call
site. Only the members the gdocs toolchain touches are stubbed; widening this
stub should be a deliberate decision (same policy as stubs/litellm).
"""

from collections.abc import Sequence

import google.auth.credentials
import google.auth.transport

class Credentials(google.auth.credentials.Credentials):
    @classmethod
    def from_service_account_file(
        cls, filename: str, *, scopes: Sequence[str] | None = ...
    ) -> Credentials: ...
    def with_subject(self, subject: str) -> Credentials: ...
    def refresh(self, request: google.auth.transport.Request) -> None: ...
