"""Every SDK call the application makes resolves to a route the fake serves (ADR 0060).

Business risk covered: a call the fake cannot answer fails an iteration
run the first time a spec reaches it — or, if no spec reaches it, waits
for the real gate or for production. Reading the application's calls off
its source and the verb and path of each off the SDK's makes the gap a
test failure here, not a discovery there.

The payroll writes and the leave and timesheet reads are the next slice;
they are named below so that the gate shrinks as they land and nothing new
slips past it unnamed.
"""

import inspect
import re
from pathlib import Path
from uuid import uuid4

from xero_python.accounting import AccountingApi
from xero_python.identity import IdentityApi
from xero_python.payrollnz import PayrollNzApi

from apps.xero.fake.router import ROUTES

APPS_DIR = Path(__file__).resolve().parents[3]
_SDK_METHOD = re.compile(r"^    def (?P<name>[a-z_]+)\(", re.MULTILINE)
_SDK_PATH = re.compile(r'url = self\.get_resource_url\(\s*"(?P<path>[^"]+)"')
_SDK_VERB = re.compile(r'call_api\(\s*url,\s*"(?P<verb>[A-Z]+)"')
# A call on an SDK client: the receiver is an ``*_api`` name, an ``api``
# attribute, a ``payroll_api()`` accessor or a freshly built ``PayrollNzApi(...)``.
# The provider's own ``update_purchase_order`` and Django's ``get_user`` share
# names with SDK methods, and the receiver is what tells them apart.
_CALL = re.compile(r"(?:[A-Za-z_]*[Aa]pi(?:\(\))?|\(get_api_client\(\)\))\.(?P<name>[a-z_]+)\(")

#: The SDK classes the application instantiates, and the host each one's paths sit under.
_APIS: dict[type, str] = {
    AccountingApi: "api.xero.com/api.xro/2.0",
    PayrollNzApi: "api.xero.com/payroll.xro/2.0",
    IdentityApi: "api.xero.com",
}

#: Calls the application makes that the fake does not yet serve, by slice.
EXPECTED_UNSERVED: frozenset[tuple[str, str]] = frozenset(
    {
        # PR B: payroll writes and their state machines, leave and timesheets.
        ("POST", "api.xero.com/payroll.xro/2.0/Employees"),
        ("PUT", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}"),
        ("POST", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}/Employment"),
        ("POST", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}/Leave"),
        ("PUT", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}/Leave/{LeaveID}"),
        ("DELETE", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}/Leave/{LeaveID}"),
        ("GET", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}/Leave"),
        ("GET", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}/LeaveTypes"),
        ("POST", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}/LeaveSetup"),
        ("POST", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}/LeaveTypes"),
        ("POST", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}/PaymentMethods"),
        ("POST", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}/SalaryAndWages"),
        ("POST", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}/Tax"),
        ("POST", "api.xero.com/payroll.xro/2.0/Employees/{EmployeeID}/Working-Patterns"),
        ("POST", "api.xero.com/payroll.xro/2.0/EarningsRates"),
        ("POST", "api.xero.com/payroll.xro/2.0/LeaveTypes"),
        ("POST", "api.xero.com/payroll.xro/2.0/PayRunCalendars"),
        ("GET", "api.xero.com/payroll.xro/2.0/PayRuns/{PayRunID}"),
        ("POST", "api.xero.com/payroll.xro/2.0/PayRuns"),
        ("GET", "api.xero.com/payroll.xro/2.0/Timesheets"),
        ("GET", "api.xero.com/payroll.xro/2.0/Timesheets/{TimesheetID}"),
        ("POST", "api.xero.com/payroll.xro/2.0/Timesheets"),
        ("DELETE", "api.xero.com/payroll.xro/2.0/Timesheets/{TimesheetID}"),
        ("POST", "api.xero.com/payroll.xro/2.0/Timesheets/{TimesheetID}/Approve"),
        ("POST", "api.xero.com/payroll.xro/2.0/Timesheets/{TimesheetID}/RevertToDraft"),
        # PR C: the connections the token grants.
        ("GET", "api.xero.com/Connections"),
    }
)


def _sdk_calls(api: type) -> dict[str, tuple[str, str]]:
    """Every method of one SDK class, resolved to the verb and path template it sends."""
    source = inspect.getsource(api)
    calls: dict[str, tuple[str, str]] = {}
    starts = list(_SDK_METHOD.finditer(source))
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(source)
        body = source[start.start() : end]
        path = _SDK_PATH.search(body)
        verb = _SDK_VERB.search(body)
        if path is None or verb is None:
            continue
        calls[start["name"]] = (verb["verb"], path["path"])
    return calls


def _application_sources() -> list[Path]:
    return [
        path
        for path in APPS_DIR.glob("**/*.py")
        if "/tests/" not in str(path)
        and "/fake/" not in str(path)
        and "/migrations/" not in str(path)
    ]


def _calls_the_application_makes() -> set[tuple[str, str, str]]:
    """(host, verb, path template) for every SDK method named in the application's source."""
    by_name: dict[str, tuple[str, str, str]] = {}
    for api, host in _APIS.items():
        for name, (verb, path) in _sdk_calls(api).items():
            by_name[name] = (host, verb, path)
    named: set[str] = set()
    for source in _application_sources():
        named.update(match["name"] for match in _CALL.finditer(source.read_text()))
    return {by_name[name] for name in named if name in by_name}


def _served(verb: str, url: str) -> bool:
    return any(
        method == verb and pattern.match(url) is not None for method, pattern, _handler in ROUTES
    )


def test_every_call_the_application_makes_is_routed_or_named() -> None:
    unserved: set[tuple[str, str]] = set()
    for host, verb, template in _calls_the_application_makes():
        # Path parameters are ids; an attachment's file name is the one exception.
        concrete = re.sub(r"\{FileName\}", "file.pdf", template)
        concrete = re.sub(r"\{[A-Za-z]+\}", str(uuid4()), concrete)
        if not _served(verb, f"{host}{concrete}"):
            unserved.add((verb, f"{host}{template}"))
    assert unserved == EXPECTED_UNSERVED, (
        f"newly unserved: {sorted(unserved - EXPECTED_UNSERVED)}; "
        f"now served, remove from EXPECTED_UNSERVED: {sorted(EXPECTED_UNSERVED - unserved)}"
    )


def test_the_application_makes_calls_at_all() -> None:
    # A regex that matched nothing would make the gate above pass vacuously.
    assert len(_calls_the_application_makes()) > 40
