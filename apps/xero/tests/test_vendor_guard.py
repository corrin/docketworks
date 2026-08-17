"""The hermetic guard must survive `from x import y`.

Opus: `_no_vendor_contact` in the root conftest is what keeps the default suite from
reaching a real vendor. It patches names, and a patch replaces one name in one
namespace — so a guard aimed at a FUNCTION only stops callers that look that
function up through its defining module at call time.

Opus: It used to be aimed at `apps.xero.auth.get_api_client`, which thirteen modules
bind at import (`payroll_push`, `sync`, `contacts`, `provider`, `transforms`,
`payroll_employees`, `seeding`, `payroll_sync`, `stock_sync`, `single_sync`,
`payroll_setup`, `oauth_views`, the xero command). It guarded exactly one
caller — `payroll_leave`, which imports inside the function — and none of the
ones it was written for.

Opus: The guard is now the SDK's transport: a method on a class, looked up on the
instance at call time, which no import style can pre-bind.
"""

from typing import Any, cast

import pytest


class TestVendorGuardCoversBoundAliases:
    def test_the_sdk_transport_refuses(self) -> None:
        """Every typed Xero call and the token refresh funnel through this."""
        from xero_python.rest import RESTClientObject  # noqa: PLC0415

        # Opus: cast: the guard replaces the method with a refusing stand-in, so the
        # real signature no longer describes what is there.
        transport = cast("Any", RESTClientObject).request
        with pytest.raises(RuntimeError, match="Xero"):
            transport("GET", "https://api.xero.com/api.xro/2.0/Contacts")

    def test_the_refusal_names_the_suite_that_may_call_a_vendor(self) -> None:
        from xero_python.rest import RESTClientObject  # noqa: PLC0415

        transport = cast("Any", RESTClientObject).request
        with pytest.raises(RuntimeError) as excinfo:
            transport("GET", "https://api.xero.com/")

        assert "integration" in str(excinfo.value)

    def test_the_raw_token_endpoint_is_guarded_too(self) -> None:
        """auth.py posts to identity.xero.com with requests, bypassing the SDK."""
        from apps.xero import auth  # noqa: PLC0415

        with pytest.raises(RuntimeError, match="Xero"):
            cast("Any", auth).requests.post("https://identity.xero.com/connect/token")

    def test_no_entry_point_is_a_pre_bindable_function(self) -> None:
        """Structural, because a guard aimed at a function passes its own tests.

        Opus: The failure is silent: the suite goes on reporting itself hermetic
        while a module that imported the name by value reaches the vendor for
        real. Only the shape of the target can catch a return to that.
        """
        import conftest  # noqa: PLC0415

        assert "apps.xero.auth.get_api_client" not in conftest._VENDOR_ENTRY_POINTS
        assert "xero_python.rest.RESTClientObject.request" in conftest._VENDOR_ENTRY_POINTS
        assert "apps.xero.auth.requests" in conftest._VENDOR_ENTRY_POINTS
