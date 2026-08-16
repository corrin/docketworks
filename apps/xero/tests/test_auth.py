"""Token lifecycle: the lazy client singleton, refresh persistence, and
tenant-id resolution.

Business risk covered: Xero rotates refresh tokens, so a refresh whose result
is not persisted strands the install with a dead token (v1 Trello #298); and
two processes racing the same refresh_token invalidate each other — hence the
shared-cache lock these tests pin.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from django.core.cache import cache
from xero_python.api_client.oauth2 import TokenApi

from apps.core.models import AppError, CompanyDefaults
from apps.xero import auth
from apps.xero.active_app import NoActiveXeroAppError
from apps.xero.constants import TENANT_ID_CACHE_KEY, XERO_SCOPES

from .conftest import make_xero_app


@pytest.fixture(autouse=True)
def _clean_auth_state() -> object:
    """Every test starts and ends with no singleton and no refresh lock."""
    auth._reset_api_client()
    auth._shared_cache.delete(auth.REFRESH_LOCK_KEY)
    yield
    auth._reset_api_client()
    auth._shared_cache.delete(auth.REFRESH_LOCK_KEY)


@pytest.mark.django_db
class TestApiClientSingleton:
    """auth.api_client is a stable proxy backed by a lazy singleton."""

    def test_proxy_is_stable(self) -> None:
        # The proxy itself never changes — `from auth import api_client`
        # captures it once and stays valid across resets.
        assert auth.api_client is auth.api_client

    def test_lazy_build_on_attribute_access(self) -> None:
        make_xero_app(client_id="a1", is_active=True, access_token="t", refresh_token="r")
        assert auth._api_client is None
        # Touch any attribute on the proxy → triggers _build() once.
        _ = auth.api_client.configuration
        assert auth._api_client is not None
        first_underlying = auth._api_client
        _ = auth.api_client.configuration  # cached: same underlying
        assert auth._api_client is first_underlying

    def test_reset_forces_rebuild_on_next_access(self) -> None:
        make_xero_app(client_id="a1", is_active=True, access_token="t", refresh_token="r")
        _ = auth.api_client.configuration
        first_underlying = auth._api_client
        auth._reset_api_client()
        _ = auth.api_client.configuration
        assert auth._api_client is not first_underlying

    def test_no_active_row_raises_on_access(self) -> None:
        # No XeroApp row at all. The proxy itself doesn't touch the DB,
        # but the first attribute access does.
        with pytest.raises(NoActiveXeroAppError):
            _ = auth.api_client.configuration


@pytest.mark.django_db
class TestRefreshTokenPersistence:
    """auth.refresh_token() must persist the new tokens to the DB row.

    Regression: TokenApi.refresh_token() is the low-level POST and does not
    invoke the bound oauth2_token_saver. Earlier v1 code returned the new
    token dict without persisting, so successful Xero refreshes were dropped
    on the floor and the stored refresh_token went stale until Xero finally
    rejected it.
    """

    def test_successful_refresh_writes_new_tokens_to_active_row(self) -> None:
        row = make_xero_app(
            client_id="a1",
            client_secret="s",
            is_active=True,
            access_token="OLD_AT",
            refresh_token="OLD_RT",
            token_type="Bearer",
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
            scope="accounting.transactions",
        )

        new_token = {
            "access_token": "NEW_AT",
            "refresh_token": "NEW_RT",
            "token_type": "Bearer",
            "expires_in": 1800,
            "scope": "accounting.transactions",
        }
        with patch.object(TokenApi, "refresh_token", return_value=dict(new_token)):
            result = auth.refresh_token()

        assert result is not None
        assert result["access_token"] == "NEW_AT"

        row.refresh_from_db()
        assert row.access_token == "NEW_AT"
        assert row.refresh_token == "NEW_RT"


@pytest.mark.django_db
class TestGetValidToken:
    def test_valid_token_returns_without_refreshing(self) -> None:
        make_xero_app(
            client_id="a1",
            client_secret="s",
            is_active=True,
            access_token="AT",
            refresh_token="RT",
            token_type="Bearer",
            expires_at=datetime.now(UTC) + timedelta(minutes=10),
            scope="accounting.transactions",
        )

        with patch.object(auth, "refresh_token") as mock_refresh:
            result = auth.get_valid_token()

        assert result is not None, "Expected a valid token payload"
        assert result["access_token"] == "AT"
        mock_refresh.assert_not_called()

    def test_expired_token_with_refresh_token_refreshes_and_persists(self) -> None:
        row = make_xero_app(
            client_id="a1",
            client_secret="s",
            is_active=True,
            access_token="OLD_AT",
            refresh_token="OLD_RT",
            token_type="Bearer",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
            scope="accounting.transactions",
        )

        new_token = {
            "access_token": "NEW_AT",
            "refresh_token": "NEW_RT",
            "token_type": "Bearer",
            "expires_in": 1800,
            "scope": "accounting.transactions",
        }
        with patch.object(TokenApi, "refresh_token", return_value=dict(new_token)):
            result = auth.get_valid_token()

        assert result is not None, "Expected a refreshed token payload"
        assert result["access_token"] == "NEW_AT"
        row.refresh_from_db()
        assert row.access_token == "NEW_AT"
        assert row.refresh_token == "NEW_RT"

    def test_expired_token_without_refresh_token_returns_none(self) -> None:
        make_xero_app(
            client_id="a1",
            client_secret="s",
            is_active=True,
            access_token="OLD_AT",
            refresh_token=None,
            token_type="Bearer",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
            scope="accounting.transactions",
        )

        assert auth.get_valid_token() is None

    def test_refresh_failure_is_persisted_and_propagated(self) -> None:
        make_xero_app(
            client_id="a1",
            client_secret="s",
            is_active=True,
            access_token="OLD_AT",
            refresh_token="OLD_RT",
            token_type="Bearer",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
            scope="accounting.transactions",
        )

        before = AppError.objects.count()
        with (
            patch.object(TokenApi, "refresh_token", side_effect=RuntimeError("boom")),
            pytest.raises(RuntimeError),
        ):
            auth.get_valid_token()

        assert AppError.objects.count() == before + 1
        assert auth._shared_cache.get(auth.REFRESH_LOCK_KEY) is None

    def test_refresh_does_not_delete_reacquired_lock(self) -> None:
        # If the refresh outlives the lock TTL and another process takes the
        # lock, the finally-branch must not delete the new owner's lock.
        row = make_xero_app(
            client_id="a1",
            client_secret="s",
            is_active=True,
            access_token="OLD_AT",
            refresh_token="OLD_RT",
            token_type="Bearer",
            expires_at=datetime.now(UTC) - timedelta(minutes=1),
            scope="accounting.transactions",
        )
        replacement_owner = f"{row.id}:replacement"

        def replace_lock() -> dict[str, object]:
            auth._shared_cache.set(
                auth.REFRESH_LOCK_KEY,
                replacement_owner,
                timeout=auth.REFRESH_LOCK_TIMEOUT_SECONDS,
            )
            return {
                "access_token": "NEW_AT",
                "refresh_token": "NEW_RT",
                "token_type": "Bearer",
                "expires_in": 1800,
                "scope": "accounting.transactions",
            }

        with patch.object(auth, "refresh_token", side_effect=replace_lock):
            result = auth.get_valid_token()

        assert result is not None, "Expected a refreshed token payload"
        assert result["access_token"] == "NEW_AT"
        assert auth._shared_cache.get(auth.REFRESH_LOCK_KEY) == replacement_owner


@pytest.mark.django_db
class TestGetTenantId:
    @pytest.fixture(autouse=True)
    def _configured_install(self) -> None:
        cache.delete(TENANT_ID_CACHE_KEY)
        company_defaults = CompanyDefaults.get_solo()
        company_defaults.xero_tenant_id = "configured-tenant"
        company_defaults.save(update_fields=["xero_tenant_id"])
        make_xero_app(
            client_id="a1",
            is_active=True,
            access_token="AT",
            refresh_token="RT",
            token_type="Bearer",
            expires_at=datetime.now(UTC) + timedelta(days=1),
            scope="accounting.contacts",
        )

    def test_uses_company_defaults_on_cache_miss(self) -> None:
        """Normal Xero calls must not discover the stable tenant over the network."""
        with patch("apps.xero.auth.IdentityApi") as mock_identity_api:
            tenant_id = auth.get_tenant_id()

        assert tenant_id == "configured-tenant"
        assert cache.get(TENANT_ID_CACHE_KEY) == "configured-tenant"
        mock_identity_api.assert_not_called()

    def test_uses_cache_before_company_defaults(self) -> None:
        """Active-app swaps own cache invalidation; ordinary reads should trust cache."""
        cache.set(TENANT_ID_CACHE_KEY, "cached-tenant")

        with (
            patch("apps.xero.auth.CompanyDefaults.get_solo") as mock_solo,
            patch("apps.xero.auth.IdentityApi") as mock_identity_api,
        ):
            tenant_id = auth.get_tenant_id()

        assert tenant_id == "cached-tenant"
        mock_solo.assert_not_called()
        mock_identity_api.assert_not_called()


class TestXeroScopes:
    def test_payroll_read_scopes_are_requested_for_get_endpoints(self) -> None:
        """Setup and restore flows read payroll settings before creating data."""
        required = {
            "payroll.timesheets.read",
            "payroll.payruns.read",
            "payroll.payslip.read",
            "payroll.employees.read",
            "payroll.settings.read",
        }

        assert required.issubset(set(XERO_SCOPES))


class TestTenantCacheSpansProcesses:
    """The tenant id is invalidated by one process and read by others.

    `swap_active`, `wipe_tokens_and_quota` and the disconnect endpoint all
    clear the key from whichever process served them, while a Celery worker
    holds its own copy. On a per-process cache none of those invalidations
    reach the worker, and the entry keeps Django's 300s default — so for up to
    five minutes after an organisation swap the worker resolves the PREVIOUS
    tenant and writes into the wrong Xero organisation.

    Structural, because a single-process suite cannot reproduce it: the reader
    and the invalidators would share one LocMem cache and agree perfectly.
    """

    def test_the_tenant_cache_is_the_shared_one(self) -> None:
        from django.core.cache import caches  # noqa: PLC0415

        from apps.xero.constants import tenant_cache  # noqa: PLC0415

        assert tenant_cache() is caches["shared"]
        assert tenant_cache() is not caches["default"]

    def test_every_tenant_cache_site_goes_through_it(self) -> None:
        """One definition, because the reader and three invalidators must agree.

        A site left on `django.core.cache.cache` still passes its own tests and
        silently stops participating in invalidation, which is how this was
        wrong in the first place.

        Read from the AST rather than the text: the key is also named in prose,
        and a scan that cannot tell code from a docstring reports the docstring.
        """
        import ast  # noqa: PLC0415
        import pathlib  # noqa: PLC0415

        repo_root = pathlib.Path(__file__).resolve().parents[3]
        offenders: list[str] = []
        for path in (repo_root / "apps" / "xero").rglob("*.py"):
            if path.name == "constants.py" or "tests" in path.parts:
                continue
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, ast.Call):
                    continue
                names = {a.id for a in node.args if isinstance(a, ast.Name)}
                if "TENANT_ID_CACHE_KEY" not in names:
                    continue
                receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
                through_accessor = (
                    isinstance(receiver, ast.Call)
                    and isinstance(receiver.func, ast.Name)
                    and receiver.func.id == "tenant_cache"
                )
                if not through_accessor:
                    offenders.append(f"{path.relative_to(repo_root)}:{node.lineno}")

        assert offenders == [], "tenant cache reached without tenant_cache(): " + ", ".join(
            offenders
        )
