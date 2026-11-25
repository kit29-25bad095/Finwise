#!/usr/bin/env bash
# ==============================================================================
# Finora — Production Automated TLS Certificate Renewal Script
# ==============================================================================
# Renews Let's Encrypt certificates via ACME webroot challenge, updates Nginx
# certificate files with strict permissions, and reloads Nginx without downtime.
# Suitable for automated execution via systemd timer or cron twice daily.
# ==============================================================================

set -euo pipefail

DOMAIN="${1:-}"
CERT_DIR="./nginx/certs"
CHALLENGE_DIR="./certbot/www"

if [ -z "${DOMAIN}" ]; then
    if [ -f ".env.production" ]; then
        DOMAIN=$(grep '^DOMAIN_NAME=' .env.production | cut -d '=' -f2 | tr -d '"' | tr -d "'" || true)
    fi
fi

if [ -z "${DOMAIN}" ]; then
    echo "[ERROR] No domain specified. Usage: ./scripts/renew_certs.sh yourdomain.com"
    exit 1
fi

echo "[INFO] Running Certbot certificate renewal for ${DOMAIN}..."

# Execute renewal via webroot challenge
sudo certbot renew --webroot -w "${CHALLENGE_DIR}" --quiet

LIVE_DIR="/etc/letsencrypt/live/${DOMAIN}"
if [ -d "${LIVE_DIR}" ]; then
    echo "[INFO] Updating Nginx TLS certificates from ${LIVE_DIR}..."
    sudo cp "${LIVE_DIR}/fullchain.pem" "${CERT_DIR}/finora.crt"
    sudo cp "${LIVE_DIR}/privkey.pem" "${CERT_DIR}/finora.key"
    sudo chmod 644 "${CERT_DIR}/finora.crt"
    sudo chmod 600 "${CERT_DIR}/finora.key"

    echo "[INFO] Reloading Nginx reverse-proxy configuration..."
    docker compose -f docker-compose.prod.yml --env-file .env.production exec -T reverse-proxy nginx -s reload
    echo "[SUCCESS] TLS certificate renewal and Nginx reload completed successfully."
else
    echo "[WARN] Let's Encrypt live directory ${LIVE_DIR} not found. Skipping certificate copy."
fi
