#!/bin/bash
set -euo pipefail

# Certbot manual cleanup hook for Dreamhost DNS.
# Called by certbot after DNS-01 challenge to remove TXT record.
#
# Requires: DREAMHOST_API_KEY env var or /etc/letsencrypt/dreamhost-api-key.txt
# Certbot provides: CERTBOT_DOMAIN, CERTBOT_VALIDATION

if [[ -n "${DREAMHOST_API_KEY:-}" ]]; then
    API_KEY="$DREAMHOST_API_KEY"
elif [[ -f /etc/letsencrypt/dreamhost-api-key.txt ]]; then
    API_KEY="$(cat /etc/letsencrypt/dreamhost-api-key.txt | tr -d '[:space:]')"
else
    echo "ERROR: No Dreamhost API key found."
    exit 1
fi

RECORD="_acme-challenge.${CERTBOT_DOMAIN}"

echo "Removing DNS TXT record: $RECORD = $CERTBOT_VALIDATION"

RESPONSE=$(curl -s "https://api.dreamhost.com/?key=${API_KEY}&cmd=dns-remove_record&record=${RECORD}&type=TXT&value=${CERTBOT_VALIDATION}")

if echo "$RESPONSE" | grep -q "success"; then
    echo "TXT record removed successfully."
else
    echo "WARNING: Failed to remove TXT record (non-fatal)."
    echo "Response: $RESPONSE"
fi
