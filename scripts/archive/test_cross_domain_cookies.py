#!/usr/bin/env python3
"""
Test script to verify cross-domain cookie configuration.

This script tests that:
1. Login endpoint sets cookies with correct SameSite=None attribute
2. Subsequent requests include the cookie
3. Backend accepts and validates the cookie

Usage:
    # Reads URLs from .env automatically
    python scripts/test_cross_domain_cookies.py

    # Or specify URLs manually
    python scripts/test_cross_domain_cookies.py --backend https://msm-workflow.ngrok-free.app --frontend https://msm-workflow-front.ngrok-free.app
"""

import argparse
import sys
from pathlib import Path

import requests
from dotenv import dotenv_values


def test_login_and_cookie(
    backend_url: str, frontend_url: str, username: str, password: str
):
    """Test login and cookie behavior."""
    print(f"\n{'='*60}")
    print("Testing Cross-Domain Cookie Configuration")
    print(f"{'='*60}\n")

    print(f"Backend URL:  {backend_url}")
    print(f"Frontend URL: {frontend_url}")
    print(f"Username:     {username}\n")

    # Use a session to maintain cookies across requests
    session = requests.Session()

    # Test 1: Login and get cookies
    print("Step 1: Logging in to get JWT cookies...")
    login_url = f"{backend_url}/accounts/api/token/"
    login_data = {"username": username, "password": password}

    try:
        response = session.post(
            login_url,
            json=login_data,
            # Simulate cross-origin request from browser
            headers={
                "Origin": frontend_url,
                "Referer": f"{frontend_url}/login",
            },
        )

        if response.status_code != 200:
            print(f"✗ Login failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return False

        print(f"✓ Login successful (status {response.status_code})")

        # Check cookies
        cookies = session.cookies
        if "access_token" not in cookies:
            print("✗ access_token cookie not found in response")
            print(f"Available cookies: {list(cookies.keys())}")
            return False

        print("✓ access_token cookie found")

        # Inspect cookie attributes from Set-Cookie header
        set_cookie_header = response.headers.get("Set-Cookie", "")
        print("\nCookie attributes:")
        print(f"  Set-Cookie header: {set_cookie_header[:200]}...")

        # Check for critical attributes
        has_secure = "Secure" in set_cookie_header
        has_httponly = "HttpOnly" in set_cookie_header
        has_samesite_none = "SameSite=None" in set_cookie_header
        has_domain = "Domain=" in set_cookie_header

        print(f"  {'✓' if has_secure else '✗'} Secure")
        print(f"  {'✓' if has_httponly else '✗'} HttpOnly")
        print(f"  {'✓' if has_samesite_none else '✗'} SameSite=None")
        print(f"  {'✓' if has_domain else '✗'} Domain attribute")

        if not has_samesite_none:
            print("\n✗ CRITICAL: SameSite=None not found in cookie!")
            print("  Cross-origin cookie sharing will NOT work.")
            return False

        if not has_secure:
            print("\n✗ CRITICAL: Secure flag not set!")
            print("  SameSite=None requires Secure flag.")
            return False

    except Exception as e:
        print(f"✗ Login request failed: {e}")
        return False

    # Test 2: Make authenticated request
    print("\nStep 2: Making authenticated request to /accounts/me/...")
    me_url = f"{backend_url}/accounts/me/"

    try:
        response = session.get(
            me_url,
            headers={
                "Origin": frontend_url,
                "Referer": f"{frontend_url}/dashboard",
            },
        )

        if response.status_code != 200:
            print(f"✗ Authenticated request failed with status {response.status_code}")
            print(f"Response: {response.text}")
            return False

        print(f"✓ Authenticated request successful (status {response.status_code})")

        # Check if we got user data
        try:
            user_data = response.json()
            if "email" in user_data:
                print(f"✓ User data received: {user_data.get('email')}")
            else:
                print(f"✗ User data incomplete: {user_data}")
                return False
        except Exception as e:
            print(f"✗ Failed to parse user data: {e}")
            return False

    except Exception as e:
        print(f"✗ Authenticated request failed: {e}")
        return False

    # Test 3: Verify cookie sent in request
    print("\nStep 3: Verifying cookie behavior...")
    print(f"  Cookies in session: {list(session.cookies.keys())}")

    if "access_token" in session.cookies:
        print("✓ access_token cookie persisted in session")
    else:
        print("✗ access_token cookie not in session")
        return False

    print(f"\n{'='*60}")
    print("✓ ALL TESTS PASSED!")
    print("Cross-domain cookie authentication is working correctly.")
    print(f"{'='*60}\n")

    return True


def read_env_file():
    """Read backend and frontend URLs from .env file using python-dotenv."""
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return None, None

    env_vars = dotenv_values(env_path)
    backend = env_vars.get("TUNNEL_URL")
    frontend = env_vars.get("FRONT_END_URL")

    return backend, frontend


def main():
    # Try to read from .env
    backend_from_env, frontend_from_env = read_env_file()

    parser = argparse.ArgumentParser(
        description="Test cross-domain cookie configuration"
    )
    parser.add_argument(
        "--backend",
        default=backend_from_env,
        help="Backend URL (default: from .env TUNNEL_URL)",
    )
    parser.add_argument(
        "--frontend",
        default=frontend_from_env,
        help="Frontend URL (default: from .env FRONT_END_URL)",
    )
    parser.add_argument(
        "--username",
        default="defaultadmin@example.com",
        help="Username for login test (default: defaultadmin@example.com)",
    )
    parser.add_argument(
        "--password",
        default="Default-admin-password",
        help="Password for login test (default: Default-admin-password)",
    )

    args = parser.parse_args()

    # Validate that we have URLs
    if not args.backend:
        parser.error(
            "Backend URL not found in .env (TUNNEL_URL) and not provided via --backend"
        )
    if not args.frontend:
        parser.error(
            "Frontend URL not found in .env (FRONT_END_URL) and not provided via --frontend"
        )

    # Validate URLs
    if not args.backend.startswith(("http://", "https://")):
        parser.error("Backend URL must start with http:// or https://")
    if not args.frontend.startswith(("http://", "https://")):
        parser.error("Frontend URL must start with http:// or https://")

    success = test_login_and_cookie(
        args.backend, args.frontend, args.username, args.password
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
