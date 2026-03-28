#!/bin/bash
set -euo pipefail

# Certbot manual auth hook for Dreamhost DNS.
# Called by certbot during DNS-01 challenge to add TXT record.
#
# Requires: DREAMHOST_API_KEY env var or /etc/letsencrypt/dreamhost-api-key.txt
# Certbot provides: CERTBOT_DOMAIN, CERTBOT_VALIDATION

if [[ -n "${DREAMHOST_API_KEY:-}" ]]; then
    API_KEY="$DREAMHOST_API_KEY"
elif [[ -f /etc/letsencrypt/dreamhost-api-key.txt ]]; then
    API_KEY="$(cat /etc/letsencrypt/dreamhost-api-key.txt | tr -d '[:space:]')"
else
    echo "ERROR: No Dreamhost API key found."
    echo "Set DREAMHOST_API_KEY env var or create /etc/letsencrypt/dreamhost-api-key.txt"
    exit 1
fi

RECORD="_acme-challenge.${CERTBOT_DOMAIN}"

echo "Adding DNS TXT record: $RECORD = $CERTBOT_VALIDATION"

RESPONSE=$(curl -s "https://api.dreamhost.com/?key=${API_KEY}&cmd=dns-add_record&record=${RECORD}&type=TXT&value=${CERTBOT_VALIDATION}")

if echo "$RESPONSE" | grep -q "success"; then
    echo "TXT record added successfully."
else
    echo "ERROR: Failed to add TXT record."
    echo "Response: $RESPONSE"
    exit 1
fi

# Dreamhost DNS propagation can be slow — wait for it
echo "Waiting 120 seconds for DNS propagation..."
sleep 120
