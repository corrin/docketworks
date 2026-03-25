#!/usr/bin/env python
"""
Test script to verify login logging functionality.

This script uses Selenium to perform actual login attempts and verifies
that the login events are properly logged to auth.log with IP addresses.

Usage:
    python scripts/test_login_logging.py
"""

import os
import sys
import time
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Setup Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "docketworks.settings")
import django

django.setup()

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# Test credentials (from docs/initial_install.md)
TEST_CREDENTIALS = {
    "valid": {
        "username": "defaultadmin@example.com",
        "password": "Default-admin-password",
    },
    "wrongpw": {
        "username": "invalid@example.com",
        "password": "wrongpassword",
    },
    "wronguser": {
        "username": "fred@example.com",
        "password": "defaultadmin",
    },
}


def test_direct_api():
    """Test login logging via direct API calls to running server."""
    print("\n" + "=" * 80)
    print("TESTING DIRECT API CALLS")
    print("=" * 80)

    api_url = "http://localhost:8000/api/accounts/token/"

    # Test 1: Failed login
    print("\nTest 1: Direct API - Failed login")
    response = requests.post(api_url, json=TEST_CREDENTIALS["wrongpw"])
    print(f"Status: {response.status_code}")

    # Test 2: Successful login
    print("\nTest 2: Direct API - Successful login")
    response = requests.post(api_url, json=TEST_CREDENTIALS["valid"])
    print(f"Status: {response.status_code}")
    time.sleep(1)


def test_selenium_frontend():
    """Test login logging via selenium through the frontend."""
    from django.conf import settings

    frontend_url = settings.FRONT_END_URL
    if not frontend_url:
        print("\nWARNING: FRONT_END_URL not set, skipping selenium tests")
        return

    login_url = f"{frontend_url}/login"

    print("\n" + "=" * 80)
    print("TESTING VIA SELENIUM/FRONTEND")
    print("=" * 80)
    print(f"Frontend URL: {frontend_url}")
    print(f"Login URL: {login_url}")

    # Setup Selenium
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)

    try:
        # Test 1: Failed login attempt
        print("\nTest 1: Selenium - Failed login attempt")
        driver.get(login_url)
        time.sleep(2)

        # Find username and password fields
        username_field = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.NAME, "username"))
        )
        password_field = driver.find_element(By.NAME, "password")

        # Enter invalid credentials
        username_field.send_keys(TEST_CREDENTIALS["wrongpw"]["username"])
        password_field.send_keys(TEST_CREDENTIALS["wrongpw"]["password"])

        # Submit form
        submit_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
        submit_button.click()

        time.sleep(2)

        # Test 2: Successful login with default test credentials
        print("Test 2: Selenium - Successful login attempt")
        driver.get(login_url)
        time.sleep(2)

        username_field = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.NAME, "username"))
        )
        password_field = driver.find_element(By.NAME, "password")

        # Use default test credentials from README
        username_field.send_keys(TEST_CREDENTIALS["valid"]["username"])
        password_field.send_keys(TEST_CREDENTIALS["valid"]["password"])

        submit_button = driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
        submit_button.click()

        time.sleep(2)

    except Exception as e:
        print(f"Selenium test failed: {e}")
    finally:
        driver.quit()


def test_login_logging():
    """Test that login attempts are logged with IP addresses."""
    # Path to auth log file
    log_file = project_root / "logs" / "auth.log"

    # Get initial log size (if file exists)
    initial_size = log_file.stat().st_size if log_file.exists() else 0

    print("Testing login logging...")
    print(f"Auth log file: {log_file}")
    print(f"Initial log size: {initial_size} bytes")

    # Test direct API calls
    test_direct_api()

    # Test via selenium/frontend
    test_selenium_frontend()

    # Wait for logs to be written
    time.sleep(1)

    # Check if auth log file was created/updated
    if not log_file.exists():
        print(f"\nERROR: Auth log file not created at {log_file}")
        return False

    # Read new log entries
    with open(log_file, "r") as f:
        f.seek(initial_size)
        new_logs = f.read()

    if not new_logs:
        print("\nERROR: No new log entries found")
        return False

    print("\n" + "=" * 80)
    print("NEW LOG ENTRIES:")
    print("=" * 80)
    print(new_logs)
    print("=" * 80)

    # Verify log format
    success = True
    if "JWT LOGIN" not in new_logs:
        print("\nERROR: Expected 'JWT LOGIN' in log entries")
        success = False

    if "ip=" not in new_logs:
        print("\nERROR: Expected 'ip=' in log entries")
        success = False

    if "username=" not in new_logs:
        print("\nERROR: Expected 'username=' in log entries")
        success = False

    if success:
        print("\n✓ Login logging test PASSED")
    else:
        print("\n✗ Login logging test FAILED")

    return success


if __name__ == "__main__":
    success = test_login_logging()
    sys.exit(0 if success else 1)
