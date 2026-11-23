#!/usr/bin/env python3
"""
Finora PostgreSQL Automated Backup Utility
==========================================
Executes non-blocking, custom-compressed physical backups (pg_dump -Fc) of Finora databases.
Computes cryptographic SHA-256 integrity checksums, validates catalog completeness via pg_restore,
and maintains backup metadata manifests.

Usage:
    python -m scripts.backup_postgres [--db finora_staging] [--out-dir ./backups] [--retention-days 7]
"""

import os
import sys
import time
import json
import hashlib
import argparse
import logging
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("backup_postgres")


def find_pg_binary(name: str) -> str:
    """Finds a PostgreSQL CLI binary (pg_dump, pg_restore, psql) across standard paths."""
    # 1. Check PATH
    import shutil
    path_bin = shutil.which(name)
    if path_bin:
        return path_bin

    # 2. Check standard Windows installations
    candidates = [
        f"C:\\Program Files\\PostgreSQL\\17\\bin\\{name}.exe",
        f"C:\\Program Files\\PostgreSQL\\16\\bin\\{name}.exe",
        f"C:\\Program Files\\PostgreSQL\\15\\bin\\{name}.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    raise FileNotFoundError(f"Could not locate PostgreSQL binary '{name}'. Ensure PostgreSQL is installed and on PATH.")


def compute_sha256(filepath: str) -> str:
    """Computes SHA-256 digest of a file in streaming chunks."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().upper()


def run_backup(
    db_name: str,
    host: str = "localhost",
    port: int = 5432,
    user: str = "finora_staging",
    password: str = "Loneliness062615",
    out_dir: str = "backups",
    retention_days: int = 7,
) -> dict:
    """
    Executes an atomic pg_dump backup, calculates checksum, verifies catalog, and logs metadata.
    """
    pg_dump_bin = find_pg_binary("pg_dump")
    pg_restore_bin = find_pg_binary("pg_restore")

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_filename = f"{db_name}_{timestamp_str}.dump"
    backup_filepath = out_path / backup_filename
    manifest_filepath = out_path / f"{db_name}_{timestamp_str}.meta.json"

    logger.info("Starting backup of database '%s' at %s:%d...", db_name, host, port)
    logger.info("Using pg_dump binary: %s", pg_dump_bin)
    logger.info("Destination archive: %s", backup_filepath)

    env = os.environ.copy()
    if password:
        env["PGPASSWORD"] = password

    start_time = time.perf_counter()

    dump_cmd = [
        pg_dump_bin,
        "-h", host,
        "-p", str(port),
        "-U", user,
        "-d", db_name,
        "-Fc",                 # Custom format (compressed, flexible restore)
        "--no-owner",          # Portability across different roles
        "--no-privileges",
        "-f", str(backup_filepath),
    ]

    res = subprocess.run(dump_cmd, env=env, capture_output=True, text=True)
    dump_duration = time.perf_counter() - start_time

    if res.returncode != 0:
        logger.error("pg_dump failed with return code %d:\n%s", res.returncode, res.stderr)
        raise RuntimeError(f"Database backup failed: {res.stderr}")

    file_size_bytes = os.path.getsize(backup_filepath)
    sha256_hash = compute_sha256(str(backup_filepath))
    logger.info("Backup created in %.2fs: Size: %d bytes (%.2f KB), SHA-256: %s",
                dump_duration, file_size_bytes, file_size_bytes / 1024, sha256_hash)

    # Catalog verification via pg_restore --list
    verify_start = time.perf_counter()
    list_cmd = [pg_restore_bin, "--list", str(backup_filepath)]
    list_res = subprocess.run(list_cmd, capture_output=True, text=True)
    verify_duration = time.perf_counter() - verify_start

    if list_res.returncode != 0:
        logger.error("Archive catalog verification failed:\n%s", list_res.stderr)
        raise RuntimeError("Backup archive is corrupted or unreadable by pg_restore.")

    catalog_lines = [l for l in list_res.stdout.splitlines() if l.strip() and not l.startswith(";")]
    catalog_object_count = len(catalog_lines)
    logger.info("Archive verified: %d catalog objects verified in %.3fs", catalog_object_count, verify_duration)

    metadata = {
        "database": db_name,
        "host": host,
        "port": port,
        "user": user,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "backup_file": str(backup_filepath),
        "file_size_bytes": file_size_bytes,
        "sha256": sha256_hash,
        "format": "PostgreSQL Custom Compressed (-Fc)",
        "pg_dump_duration_seconds": round(dump_duration, 3),
        "verification_duration_seconds": round(verify_duration, 3),
        "catalog_objects_count": catalog_object_count,
        "status": "VERIFIED",
    }

    with open(manifest_filepath, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    logger.info("Backup metadata manifest saved to %s", manifest_filepath)

    # Prune old backups according to retention policy
    if retention_days > 0:
        _prune_old_backups(out_path, db_name, retention_days)

    return metadata


def _prune_old_backups(out_path: Path, db_name: str, retention_days: int):
    """Deletes backups older than retention_days for the specified database."""
    now = time.time()
    cutoff = now - (retention_days * 86400)
    pruned = 0
    for file in out_path.glob(f"{db_name}_*.dump"):
        if file.stat().st_mtime < cutoff:
            meta_file = file.with_suffix(".meta.json")
            file.unlink(missing_ok=True)
            meta_file.unlink(missing_ok=True)
            pruned += 1
            logger.info("Pruned expired backup: %s (> %d days old)", file.name, retention_days)
    if pruned:
        logger.info("Retention cleanup: pruned %d expired backups.", pruned)


def main():
    parser = argparse.ArgumentParser(description="Finora PostgreSQL Backup Tool")
    parser.add_argument("--db", default=os.getenv("PGDATABASE", "finora_test"), help="Database name")
    parser.add_argument("--host", default=os.getenv("PGHOST", "localhost"), help="PostgreSQL host")
    parser.add_argument("--port", type=int, default=int(os.getenv("PGPORT", "5432")), help="PostgreSQL port")
    parser.add_argument("--user", default=os.getenv("PGUSER", "finora_staging"), help="PostgreSQL user")
    parser.add_argument("--password", default=os.getenv("PGPASSWORD", "Loneliness062615"), help="PostgreSQL password")
    parser.add_argument("--out-dir", default="backups", help="Destination directory for backups")
    parser.add_argument("--retention-days", type=int, default=7, help="Days to retain daily backups")

    args = parser.parse_args()

    try:
        run_backup(
            db_name=args.db,
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            out_dir=args.out_dir,
            retention_days=args.retention_days,
        )
    except Exception as e:
        logger.error("Backup failed: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
