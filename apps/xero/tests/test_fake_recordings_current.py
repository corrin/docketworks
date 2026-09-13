"""The fake Xero's recordings still describe what the tenant sends (ADR 0060).

Business risk covered: the fake answers E2E iteration runs from these
recordings, so a route whose wire shape has moved — a renamed key, a date
that changed format, a status that changed — would go on passing every
iteration run and fail only at the real gate, or in production. Re-fetching
each recorded route and comparing shapes is what turns that into an alarm.

Integration: reaches the real dev tenant through the same catalogue the
recorder writes from, so the two cannot describe different routes. About
thirty calls; values are not compared, only the shape of what came back.
"""

import json
from pathlib import Path

import pytest

from apps.xero.auth import get_api_client, get_tenant_id
from apps.xero.fake.recordings.catalogue import Capture, capture_all
from apps.xero.fake.wire import Json
from apps.xero.operator_guards import assert_not_production_target

RECORDINGS_DIR = Path(__file__).resolve().parent.parent / "fake" / "recordings"

pytestmark = [pytest.mark.integration, pytest.mark.django_db]


def shape_of(value: Json) -> Json:
    """Reduce a body to the shape the fake and the SDK depend on.

    Every string becomes the name of its wire format (a Microsoft date, an
    ISO date, an ISO datetime, or plain text), every number and bool its
    type, and a list is judged by its first element — the second is the same
    shape or the recording would not have kept it.
    """
    if isinstance(value, dict):
        return {key: shape_of(item) for key, item in value.items()}
    if isinstance(value, list):
        return [shape_of(value[0])] if value else []
    if isinstance(value, str):
        return _string_shape(value)
    if isinstance(value, bool):
        return "<bool>"
    if value is None:
        return None
    return "<number>"


def _string_shape(value: str) -> str:
    if value.startswith("/Date("):
        return "<ms-date>"
    if len(value) >= 10 and value[4] == "-" and value[7] == "-" and value[:4].isdigit():
        return "<iso-datetime>" if "T" in value else "<iso-date>"
    return "<str>"


def _recorded(name: str) -> dict[str, Json]:
    document = json.loads((RECORDINGS_DIR / f"{name}.json").read_text())
    if not isinstance(document, dict):
        raise TypeError(f"{name}.json is not a recording document")
    return document


def _describe(capture: Capture) -> dict[str, Json]:
    return {
        "request": {"method": capture.method, "path_family": _path_family(capture.path)},
        "response": {"status": capture.status, "content_type": capture.content_type},
        "shape": shape_of(capture.body),
    }


def _path_family(path: str) -> str:
    # Ids change with every replacement of the demo organisation; the path
    # with its ids blanked is what stays comparable.
    return "/".join(
        "{id}" if len(part) == 36 and part.count("-") == 4 else part for part in path.split("/")
    )


def test_every_recorded_route_still_has_the_recorded_shape() -> None:
    assert_not_production_target()
    drifted: list[str] = []
    seen: set[str] = set()
    for live in capture_all(get_api_client(), get_tenant_id()):
        seen.add(live.name)
        recorded = _recorded(live.name)
        recorded_request = recorded["request"]
        recorded_response = recorded["response"]
        if not isinstance(recorded_request, dict) or not isinstance(recorded_response, dict):
            raise TypeError(f"{live.name}.json has no request/response block")
        expected = {
            "request": {
                "method": recorded_request["method"],
                "path_family": _path_family(str(recorded_request["path"])),
            },
            "response": {
                "status": recorded_response["status"],
                "content_type": recorded_response["content_type"],
            },
            "shape": shape_of(recorded["body"]),
        }
        actual = _describe(live)
        if actual != expected:
            drifted.append(
                f"{live.name}: recorded {json.dumps(expected, sort_keys=True)}\n"
                f"          live {json.dumps(actual, sort_keys=True)}"
            )
    on_disk = {path.stem for path in RECORDINGS_DIR.glob("*.json")}
    assert on_disk == seen, (
        f"recordings on disk {sorted(on_disk)} != routes captured {sorted(seen)}"
    )
    assert not drifted, (
        "Xero's wire shape has moved; re-record with scripts/ops/record_xero_wire.py:\n"
        + "\n".join(drifted)
    )
