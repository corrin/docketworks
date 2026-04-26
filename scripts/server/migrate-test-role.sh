#!/bin/bash
set -euo pipefail

# One-off migration: provision a per-tenant pytest role + test DB for an
# instance created before per-tenant test roles existed.
#
# Pre-this-change, all tenants on a UAT box shared a cluster-wide `dw_test`
# role with CREATEDB. This script gives one tenant its own `dw_<inst>_test`
# role (no CREATEDB) plus a pre-provisioned `test_dw_<inst>` DB it owns,
# and appends the new credentials to the instance's .env.
#
# Run once per pre-existing instance. After every instance has been
# migrated, drop the shared role:
#   sudo -u postgres psql -c "DROP ROLE dw_test;"
#
# Usage:
#   sudo scripts/server/migrate-test-role.sh <instance-name>
# Example:
#   sudo scripts/server/migrate-test-role.sh msm-uat

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <instance-name>"
    echo "Example: $0 msm-uat"
    exit 1
fi

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)."
    exit 1
fi

INSTANCE="$1"
# msm-uat → dw_msm_uat_test (role), test_dw_msm_uat (db)
INSTANCE_UNDERSCORE="${INSTANCE//-/_}"
TEST_DB_USER="dw_${INSTANCE_UNDERSCORE}_test"
TEST_DB_NAME="test_dw_${INSTANCE_UNDERSCORE}"
INSTANCE_DIR="/opt/docketworks/instances/$INSTANCE"
ENV_FILE="$INSTANCE_DIR/.env"

if [[ ! -d "$INSTANCE_DIR" ]]; then
    echo "ERROR: Instance directory $INSTANCE_DIR not found."
    exit 1
fi
if [[ ! -f "$ENV_FILE" ]]; then
    echo "ERROR: $ENV_FILE not found."
    exit 1
fi
if grep -q '^TEST_DB_USER=' "$ENV_FILE"; then
    echo "ERROR: $ENV_FILE already has a TEST_DB_USER line — looks already migrated."
    echo "  If you need to redo the migration, edit .env to remove TEST_DB_* lines"
    echo "  and DROP the existing $TEST_DB_USER role + $TEST_DB_NAME database first."
    exit 1
fi

if sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='$TEST_DB_USER';" | grep -q 1; then
    echo "ERROR: Role $TEST_DB_USER already exists in the cluster but .env doesn't"
    echo "  reference it. Partial state — investigate before re-running."
    exit 1
fi
if sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$TEST_DB_NAME';" | grep -q 1; then
    echo "ERROR: Database $TEST_DB_NAME already exists in the cluster but .env"
    echo "  doesn't reference it. Partial state — investigate before re-running."
    exit 1
fi

password=$(openssl rand -hex 16)
INSTANCE_USER="$(stat -c '%U' "$ENV_FILE")"

echo "Migrating $INSTANCE:"
echo "  Test role: $TEST_DB_USER"
echo "  Test DB:   $TEST_DB_NAME"
echo "  .env:      $ENV_FILE (owner: $INSTANCE_USER)"

sudo -u postgres psql -c "CREATE ROLE \"$TEST_DB_USER\" WITH LOGIN PASSWORD '$password';"
sudo -u postgres createdb "$TEST_DB_NAME" -O "$TEST_DB_USER"

# Append as the instance user so the file's ownership/perms are unchanged.
sudo -u "$INSTANCE_USER" tee -a "$ENV_FILE" > /dev/null <<APPEND

# Pytest connects as a separate role that owns only test_dw_<instance>.
TEST_DB_USER=$TEST_DB_USER
TEST_DB_PASSWORD=$password
APPEND

echo ""
echo "Done. Verify with:"
echo "  sudo scripts/server/dw-run.sh $INSTANCE poetry run pytest apps/accounts/tests/test_automation_user.py -v"
echo ""
echo "Once every instance on this cluster has been migrated:"
echo "  sudo -u postgres psql -c \"DROP ROLE dw_test;\""
