#!/usr/bin/env bash
# ==============================================================================
# Finora — SSL / TLS Certificate Bootstrap Script for AWS Lightsail
# ==============================================================================
# Ensures Nginx can start immediately on initial deployment by creating a
# temporary self-signed certificate if Let's Encrypt certificates are not yet present.
# ==============================================================================

set -euo pipefail

CERT_DIR="./nginx/certs"
DOMAIN="${1:-}"

mkdir -p "${CERT_DIR}"

if [ ! -f "${CERT_DIR}/finora.crt" ] || [ ! -f "${CERT_DIR}/finora.key" ]; then
    echo "[INFO] No existing SSL certificate found. Generating self-signed bootstrap certificate..."
    openssl req -x509 -nodes -newkey rsa:2048 -days 30 \
        -keyout "${CERT_DIR}/finora.key" \
        -out "${CERT_DIR}/finora.crt" \
        -subj "/C=IN/ST=Maharashtra/L=Mumbai/O=Finora/OU=Release/CN=${DOMAIN:-localhost}"
    chmod 600 "${CERT_DIR}/finora.key"
    chmod 644 "${CERT_DIR}/finora.crt"
    echo "[SUCCESS] Self-signed bootstrap certificate created in ${CERT_DIR}."
else
    echo "[INFO] Existing SSL certificates verified in ${CERT_DIR}."
fi
