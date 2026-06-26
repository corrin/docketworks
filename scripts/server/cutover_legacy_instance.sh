#!/bin/bash
set -euo pipefail

# Usage: cutover_legacy_instance.sh <instance>
# Example: cutover_legacy_instance.sh msm-uat
#
# Takes a restorable snapshot of a legacy per-instance checkout, then
# exec-s into deploy.sh for the actual cutover to shared immutable releases.
# The snapshot is the rollback target — the legacy SHA cannot be built as a
# shared release.
#
# Must run as root. One-time use per legacy instance; retire after the last
# legacy instance (msm-prod) migrates.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/common.sh"
source "$SCRIPT_DIR/release-utils.sh"

if [[ $EUID -ne 0 ]]; then
    echo "ERROR: This script must be run as root (use sudo)." >&2
    exit 1
fi

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <instance>"
    echo "Example: $0 msm-uat"
    exit 1
fi

INSTANCE="$1"
INSTANCE_DIR="$INSTANCES_DIR/$INSTANCE"
BACKUP_DIR="$INSTANCE_DIR/backups"
INST_USER="$(instance_user "$INSTANCE")"

if [[ ! -d "$INSTANCE_DIR" ]]; then
    echo "ERROR: Instance directory $INSTANCE_DIR does not exist." >&2
    exit 1
fi

if [[ ! -f "$INSTANCE_DIR/.env" ]]; then
    echo "ERROR: No .env file found at $INSTANCE_DIR/.env" >&2
    exit 1
fi

# Assert this is a legacy instance: must have .git and NO current symlink.
if [[ ! -d "$INSTANCE_DIR/.git" ]]; then
    echo "ERROR: $INSTANCE_DIR is not a legacy checkout (no .git directory)." >&2
    echo "Use 'deploy.sh $INSTANCE' for instances already on shared releases." >&2
    exit 1
fi

if [[ -L "$INSTANCE_DIR/current" ]]; then
    echo "ERROR: $INSTANCE_DIR already has a current symlink — not a legacy instance." >&2
    echo "Use 'deploy.sh $INSTANCE' for instances already on shared releases." >&2
    exit 1
fi

OLD_SHA="$(sudo -u "$INST_USER" git -C "$INSTANCE_DIR" rev-parse HEAD)"
OLD_SHORT="${OLD_SHA:0:12}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
log "Legacy instance $INSTANCE at $OLD_SHORT — taking cutover snapshot..."

mkdir -p "$BACKUP_DIR"

SNAPSHOT="$BACKUP_DIR/legacy_${OLD_SHORT}.tar.gz"
UNITS_DIR="$BACKUP_DIR/legacy_${OLD_SHORT}.units"
NGINX_BACKUP="$BACKUP_DIR/legacy_${OLD_SHORT}.nginx.conf"
MANIFEST="$BACKUP_DIR/legacy_${OLD_SHORT}.manifest"

# Snapshot the full code tree including frontend/dist, frontend/dist-manual,
# and .git. Exclude data dirs that are either large regenerable runtime state
# or already backed up separately.
log "  Creating code snapshot: $SNAPSHOT"
tar -czf "$SNAPSHOT" \
    -C "$INSTANCE_DIR" \
    --exclude='./dropbox' \
    --exclude='./mediafiles' \
    --exclude='./phone-recordings' \
    --exclude='./session-replays' \
    --exclude='./backups' \
    --exclude='./node_modules' \
    --exclude='./.cache' \
    --exclude='./logs' \
    .

chown "$INST_USER:$INST_USER" "$SNAPSHOT"

# Save the three systemd unit files.
log "  Saving systemd unit files -> $UNITS_DIR"
mkdir -p "$UNITS_DIR"
for unit in gunicorn celery-worker celery-beat; do
    unit_path="/etc/systemd/system/${unit}-${INSTANCE}.service"
    if [[ ! -f "$unit_path" ]]; then
        echo "ERROR: Required unit file not found: $unit_path" >&2
        echo "Snapshot is incomplete; run instance.sh or restore the unit before cutover." >&2
        exit 1
    fi
    cp "$unit_path" "$UNITS_DIR/"
done

# Save the nginx server config.
NGINX_CONF="/etc/nginx/sites-available/docketworks-$INSTANCE"
if [[ ! -f "$NGINX_CONF" ]]; then
    echo "ERROR: Required nginx config not found: $NGINX_CONF" >&2
    echo "Snapshot is incomplete; run instance.sh or restore the config before cutover." >&2
    exit 1
fi
log "  Saving nginx config -> $NGINX_BACKUP"
cp "$NGINX_CONF" "$NGINX_BACKUP"

# Write manifest.
cat > "$MANIFEST" <<EOF
oldsha=${OLD_SHA}
timestamp=${TIMESTAMP}
instance=${INSTANCE}
predeploy_pattern=predeploy_*_${OLD_SHORT}.sql.gz
EOF

log "  Manifest written to $MANIFEST"
log "Snapshot complete. Executing deploy..."

# Hand off to deploy.sh. The predeploy DB backup (keyed by the pre-switch
# SHA) is taken by deploy.sh before anything destructive. The operator
# passes any extra flags through.
exec "$SCRIPT_DIR/deploy.sh" "$@"
