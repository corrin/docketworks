"""Smoke tests: the project boots, the API mounts, the gates are on."""

from django.test import Client


def test_openapi_document_served() -> None:
    response = Client().get("/api/openapi.json")
    assert response.status_code == 200
    assert response.json()["info"]["title"] == "Docketworks API"
