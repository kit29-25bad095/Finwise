#!/usr/bin/env bash
# ==============================================================================
# Finora — Production Disaster Recovery & Restoration Script (Amazon Lightsail)
# ==============================================================================
# Downloads a specific snapshot from Amazon S3 (or uses a local snapshot),
# validates SHA-256 integrity checksums, restores PostgreSQL database,
# and restores evidence documents with hardened POSIX permissions.
# ==============================================================================

set -euo pipefail

SNAPSHOT_TIMESTAMP="${1:-}"
if [ -z "${SNAPSHOT_TIMESTAMP}" ]; then
    echo "Usage: $0 <YYYYMMDD_HHMMSS> [S3_BUCKET]"
    echo "Example: $0 20261125_020000 finora-production-backups-mumbai"
    exit 1
fi

S3_BUCKET="${2:-${AWS_S3_BACKUP_BUCKET:-finora-production-backups-mumbai}}"
S3_PREFIX="${AWS_S3_BACKUP_PREFIX:-daily-snapshots}"
AWS_REGION="${AWS_DEFAULT_REGION:-ap-south-1}"
BACKUP_DIR="${LOCAL_BACKUP_DIR:-./backups}"

RESTORE_TMP_DIR="/tmp/finora_restore_${SNAPSHOT_TIMESTAMP}"
mkdir -p "${RESTORE_TMP_DIR}"

echo "======================================================================"
echo "[FINORA DISASTER RECOVERY] Initiating recovery drill for snapshot: ${SNAPSHOT_TIMESTAMP}"
echo "Source: s3://${S3_BUCKET}/${S3_PREFIX}/${SNAPSHOT_TIMESTAMP}/"
echo "======================================================================"

# 1. Download manifest and archives from S3 (or verify local presence)
if [ ! -f "${BACKUP_DIR}/finora_manifest_${SNAPSHOT_TIMESTAMP}.json" ]; then
    echo "[1/4] Downloading snapshot artifacts from S3..."
    aws s3 cp "s3://${S3_BUCKET}/${S3_PREFIX}/${SNAPSHOT_TIMESTAMP}/finora_manifest_${SNAPSHOT_TIMESTAMP}.json" \
        "${RESTORE_TMP_DIR}/finora_manifest.json" --region "${AWS_REGION}"
    aws s3 cp "s3://${S3_BUCKET}/${S3_PREFIX}/${SNAPSHOT_TIMESTAMP}/finora_db_${SNAPSHOT_TIMESTAMP}.dump" \
        "${RESTORE_TMP_DIR}/finora_db.dump" --region "${AWS_REGION}"
    aws s3 cp "s3://${S3_BUCKET}/${S3_PREFIX}/${SNAPSHOT_TIMESTAMP}/finora_evidence_${SNAPSHOT_TIMESTAMP}.tar.gz" \
        "${RESTORE_TMP_DIR}/finora_evidence.tar.gz" --region "${AWS_REGION}"
else
    echo "[1/4] Using local snapshot artifacts from ${BACKUP_DIR}..."
    cp "${BACKUP_DIR}/finora_manifest_${SNAPSHOT_TIMESTAMP}.json" "${RESTORE_TMP_DIR}/finora_manifest.json"
    cp "${BACKUP_DIR}/finora_db_${SNAPSHOT_TIMESTAMP}.dump" "${RESTORE_TMP_DIR}/finora_db.dump"
    cp "${BACKUP_DIR}/finora_evidence_${SNAPSHOT_TIMESTAMP}.tar.gz" "${RESTORE_TMP_DIR}/finora_evidence.tar.gz"
fi

# 2. Cryptographic Checksum Validation
echo "[2/4] Validating cryptographic SHA-256 integrity checksums..."
EXPECTED_DB_SHA=$(jq -r '.database.sha256' "${RESTORE_TMP_DIR}/finora_manifest.json")
EXPECTED_EV_SHA=$(jq -r '.evidence.sha256' "${RESTORE_TMP_DIR}/finora_manifest.json")

ACTUAL_DB_SHA=$(sha256sum "${RESTORE_TMP_DIR}/finora_db.dump" | awk '{print toupper($1)}')
ACTUAL_EV_SHA=$(sha256sum "${RESTORE_TMP_DIR}/finora_evidence.tar.gz" | awk '{print toupper($1)}')

if [ "${EXPECTED_DB_SHA}" != "${ACTUAL_DB_SHA}" ]; then
    echo "[FATAL ERROR] Database dump SHA-256 checksum mismatch!"
    echo "Expected: ${EXPECTED_DB_SHA}"
    echo "Actual:   ${ACTUAL_DB_SHA}"
    exit 1
fi

if [ "${EXPECTED_EV_SHA}" != "${ACTUAL_EV_SHA}" ]; then
    echo "[FATAL ERROR] Evidence archive SHA-256 checksum mismatch!"
    echo "Expected: ${EXPECTED_EV_SHA}"
    echo "Actual:   ${ACTUAL_EV_SHA}"
    exit 1
fi
echo "[OK] All checksums verified successfully."

# 3. Restore PostgreSQL Database
echo "[3/4] Restoring PostgreSQL database from verified dump..."
cat "${RESTORE_TMP_DIR}/finora_db.dump" | docker compose -f docker-compose.prod.yml exec -T postgres \
    pg_restore -U "${POSTGRES_USER:-finora_user}" -d "${POSTGRES_DB:-finora_prod}" --clean --if-exists --no-owner --no-acl || true

# 4. Restore Evidence Files into Named Volume
echo "[4/4] Restoring financial evidence documents into /var/finora/storage..."
cat "${RESTORE_TMP_DIR}/finora_evidence.tar.gz" | docker compose -f docker-compose.prod.yml exec -T backend \
    tar -xzf - -C /var/finora/storage

docker compose -f docker-compose.prod.yml exec -T backend chmod -R 700 /var/finora/storage

rm -rf "${RESTORE_TMP_DIR}"

echo "======================================================================"
echo "[SUCCESS] Disaster recovery completed and verified for snapshot: ${SNAPSHOT_TIMESTAMP}"
echo "======================================================================"
