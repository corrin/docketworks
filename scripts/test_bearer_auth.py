#!/usr/bin/env python3
"""
Test bearer token authentication implementation.

Usage:
    python scripts/test_bearer_auth.py
    python scripts/test_bearer_auth.py test_bearer_disabled
    python scripts/test_bearer_auth.py test_bearer_enabled test_cookie_auth
"""

import argparse
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values


def print_test(name, passed, message):
    symbol = "✓" if passed else "✗"
    print(f"{symbol} {name}: {message}")
    return passed


def test_bearer_disabled(backend_url, username, password):
    """Bearer token endpoint returns 403 when ALLOW_BEARER_TOKEN_AUTHENTICATION=False."""
    try:
        response = requests.post(
            f"{backend_url}/accounts/api/bearer-token/",
            json={"username": username, "password": password},
            timeout=5,
        )

        if response.status_code == 403:
            data = response.json()
            if "Bearer tokens are disabled" in data.get("detail", ""):
                return print_test(
                    "test_bearer_disabled", True, "Returns 403 as expected"
                )

        return print_test(
            "test_bearer_disabled", False, f"Expected 403, got {response.status_code}"
        )
    except Exception as e:
        return print_test("test_bearer_disabled", False, f"Error: {e}")


def test_bearer_ignored_when_disabled(backend_url, username, password):
    """Bearer tokens in Authorization header are ignored when disabled."""
    try:
        response = requests.get(
            f"{backend_url}/accounts/me/",
            headers={"Authorization": "Bearer fake-token"},
            timeout=5,
        )

        passed = response.status_code == 401
        return print_test(
            "test_bearer_ignored_when_disabled",
            passed,
            f"Returns 401 (token ignored): {passed}",
        )
    except Exception as e:
        return print_test("test_bearer_ignored_when_disabled", False, f"Error: {e}")


def test_bearer_token_generation(backend_url, username, password):
    """Can generate bearer token when ALLOW_BEARER_TOKEN_AUTHENTICATION=True."""
    try:
        response = requests.post(
            f"{backend_url}/accounts/api/bearer-token/",
            json={"username": username, "password": password},
            timeout=5,
        )

        if response.status_code == 200:
            token = response.json().get("token")
            if token:
                return print_test(
                    "test_bearer_token_generation",
                    True,
                    f"Token generated (length: {len(token)})",
                )

        return print_test(
            "test_bearer_token_generation",
            False,
            f"Expected 200, got {response.status_code}",
        )
    except Exception as e:
        return print_test("test_bearer_token_generation", False, f"Error: {e}")


def test_bearer_token_authentication(backend_url, username, password):
    """Can authenticate with bearer token."""
    try:
        # Get token
        response = requests.post(
            f"{backend_url}/accounts/api/bearer-token/",
            json={"username": username, "password": password},
            timeout=5,
        )

        if response.status_code != 200:
            return print_test(
                "test_bearer_token_authentication", False, "Failed to get token"
            )

        token = response.json().get("token")
        if not token:
            return print_test(
                "test_bearer_token_authentication", False, "No token in response"
            )

        # Use token
        response = requests.get(
            f"{backend_url}/accounts/me/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )

        if response.status_code == 200:
            email = response.json().get("email")
            return print_test(
                "test_bearer_token_authentication", True, f"Authenticated as {email}"
            )

        return print_test(
            "test_bearer_token_authentication",
            False,
            f"Expected 200, got {response.status_code}",
        )
    except Exception as e:
        return print_test("test_bearer_token_authentication", False, f"Error: {e}")


def test_invalid_bearer_token_rejected(backend_url, username, password):
    """Invalid bearer token is rejected."""
    try:
        response = requests.get(
            f"{backend_url}/accounts/me/",
            headers={"Authorization": "Bearer invalid-token-12345"},
            timeout=5,
        )

        passed = response.status_code == 401
        return print_test(
            "test_invalid_bearer_token_rejected", passed, f"Returns 401: {passed}"
        )
    except Exception as e:
        return print_test("test_invalid_bearer_token_rejected", False, f"Error: {e}")


def test_cookie_auth_still_works(backend_url, username, password):
    """Cookie-based authentication still works alongside bearer tokens."""
    try:
        session = requests.Session()

        # Login with cookies
        response = session.post(
            f"{backend_url}/accounts/api/token/",
            json={"username": username, "password": password},
            timeout=5,
        )

        if response.status_code != 200:
            return print_test("test_cookie_auth_still_works", False, "Login failed")

        # Use cookie
        response = session.get(f"{backend_url}/accounts/me/", timeout=5)

        if response.status_code == 200:
            email = response.json().get("email")
            return print_test(
                "test_cookie_auth_still_works", True, f"Cookie auth works: {email}"
            )

        return print_test(
            "test_cookie_auth_still_works",
            False,
            f"Expected 200, got {response.status_code}",
        )
    except Exception as e:
        return print_test("test_cookie_auth_still_works", False, f"Error: {e}")


def test_bearer_invalid_credentials(backend_url, username, password):
    """Bearer token endpoint rejects invalid credentials."""
    try:
        response = requests.post(
            f"{backend_url}/accounts/api/bearer-token/",
            json={"username": username, "password": "wrong-password"},
            timeout=5,
        )

        passed = response.status_code == 401
        return print_test(
            "test_bearer_invalid_credentials", passed, f"Returns 401: {passed}"
        )
    except Exception as e:
        return print_test("test_bearer_invalid_credentials", False, f"Error: {e}")


def read_env_file():
    """Read URL from .env file."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return None

    env_vars = dotenv_values(env_path)
    return env_vars.get("TUNNEL_URL", "http://localhost:8000")


def main():
    backend_from_env = read_env_file()

    parser = argparse.ArgumentParser(description="Test bearer token authentication")
    parser.add_argument("tests", nargs="*", help="Specific tests to run")
    parser.add_argument("--backend", default=backend_from_env, help="Backend URL")
    parser.add_argument(
        "--username", default="defaultadmin@example.com", help="Username"
    )
    parser.add_argument("--password", default="Default-admin-password", help="Password")

    args = parser.parse_args()

    if not args.backend:
        print("Error: Backend URL not found")
        return 1

    print(f"Backend:  {args.backend}")
    print(f"Username: {args.username}\n")

    # All available tests
    all_tests = {
        "test_bearer_disabled": test_bearer_disabled,
        "test_bearer_ignored_when_disabled": test_bearer_ignored_when_disabled,
        "test_bearer_token_generation": test_bearer_token_generation,
        "test_bearer_token_authentication": test_bearer_token_authentication,
        "test_invalid_bearer_token_rejected": test_invalid_bearer_token_rejected,
        "test_cookie_auth_still_works": test_cookie_auth_still_works,
        "test_bearer_invalid_credentials": test_bearer_invalid_credentials,
    }

    # Determine which tests to run
    if args.tests:
        tests_to_run = {}
        for test_name in args.tests:
            if test_name in all_tests:
                tests_to_run[test_name] = all_tests[test_name]
            else:
                print(f"Unknown test: {test_name}")
                print(f"Available tests: {', '.join(all_tests.keys())}")
                return 1
    else:
        tests_to_run = all_tests

    # Run tests
    results = []
    for test_name, test_func in tests_to_run.items():
        results.append(test_func(args.backend, args.username, args.password))

    # Summary
    passed = sum(results)
    total = len(results)
    print(f"\n{passed}/{total} tests passed")

    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
