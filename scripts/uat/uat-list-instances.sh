#!/bin/bash

# Lists all UAT/demo instances with their status.
# Usage: uat-list-instances.sh

BASE_DIR="/opt/docketworks"
INSTANCES_DIR="$BASE_DIR/instances"
DOMAIN="docketworks.site"

if [[ ! -d "$INSTANCES_DIR" ]]; then
    echo "No instances found (directory $INSTANCES_DIR does not exist)."
    exit 0
fi

INSTANCES=()
for dir in "$INSTANCES_DIR"/*/; do
    [[ -d "$dir" ]] || continue
    name="$(basename "$dir")"
    INSTANCES+=("$name")
done

if [[ ${#INSTANCES[@]} -eq 0 ]]; then
    echo "No instances found."
    exit 0
fi

printf "%-15s %-12s %-40s\n" "INSTANCE" "STATUS" "URL"
printf "%-15s %-12s %-40s\n" "--------" "------" "---"

for name in "${INSTANCES[@]}"; do
    if systemctl is-active --quiet "gunicorn-$name" 2>/dev/null; then
        status="running"
    elif systemctl is-enabled --quiet "gunicorn-$name" 2>/dev/null; then
        status="stopped"
    else
        status="no service"
    fi
    printf "%-15s %-12s %-40s\n" "$name" "$status" "https://$name.$DOMAIN"
done
