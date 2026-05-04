"""Remove the xero-sync.service systemd unit.

The xero-sync.service systemd unit (originally created by migration 0083) is
replaced by the Beat-scheduled xero_regular_sync_task. This migration stops +
disables + removes the unit file from /etc/systemd/system on every host where
it was installed.

Idempotent: silently skip when the unit isn't present (dev / test / hosts that
never installed it). Reverse migration is a no-op — re-creating the unit would
re-instate the retired architecture.
"""

import logging
import platform
import subprocess
from pathlib import Path

from django.db import migrations

logger = logging.getLogger(__name__)


def remove_systemd_service(apps, schema_editor):
    if platform.system() != "Linux":
        logger.info("Not on Linux, skipping xero-sync.service removal")
        return

    service_path = Path("/etc/systemd/system/xero-sync.service")
    if not service_path.exists():
        logger.info("xero-sync.service not present, nothing to remove")
        return

    sudo_check = subprocess.run(["sudo", "-n", "true"], capture_output=True, text=True)
    if sudo_check.returncode != 0:
        logger.warning(
            "No passwordless sudo; xero-sync.service still present at %s. "
            "Operator action required: sudo systemctl stop xero-sync && "
            "sudo systemctl disable xero-sync && sudo rm %s && "
            "sudo systemctl daemon-reload",
            service_path,
            service_path,
        )
        return

    subprocess.run(
        ["sudo", "systemctl", "stop", "xero-sync.service"],
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["sudo", "systemctl", "disable", "xero-sync.service"],
        capture_output=True,
        text=True,
    )
    subprocess.run(["sudo", "rm", "-f", str(service_path)], check=True)
    subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
    logger.info("Removed xero-sync.service unit and reloaded systemd")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("workflow", "0221_drop_django_apscheduler_tables"),
    ]

    operations = [
        migrations.RunPython(remove_systemd_service, noop),
    ]
