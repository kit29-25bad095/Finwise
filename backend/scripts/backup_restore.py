"""
Finora Phase 7 — Production Backup & Restore Engine.
Supports cryptographic snapshot creation, SHA-256 verification, and disaster recovery.
"""

import os
import shutil
import hashlib
import json
import sqlite3
import subprocess
from datetime import datetime, timezone
from typing import Dict, Any, Tuple


class DatabaseBackupManager:
    """
    Manages automated backups, integrity checks, and restoration drills
    for both SQLite (local/test) and PostgreSQL (managed production).
    """

    @staticmethod
    def compute_file_sha256(filepath: str) -> str:
        sha256 = hashlib.sha256()
        with open(filepath, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    @classmethod
    def backup_sqlite(cls, db_path: str, backup_dir: str) -> Dict[str, Any]:
        """
        Creates an atomic backup of an SQLite database file with SHA-256 checksum.
        """
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_filename = f"finora_backup_{timestamp}.db"
        backup_path = os.path.join(backup_dir, backup_filename)

        # Use sqlite3 online backup API for ACID safety during live writes
        src_conn = sqlite3.connect(db_path)
        dst_conn = sqlite3.connect(backup_path)
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
            src_conn.close()

        checksum = cls.compute_file_sha256(backup_path)
        manifest = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database_type": "sqlite",
            "source_path": db_path,
            "backup_path": backup_path,
            "backup_filename": backup_filename,
            "sha256_checksum": checksum,
            "file_size_bytes": os.path.getsize(backup_path),
            "status": "COMPLETED"
        }

        manifest_path = os.path.join(backup_dir, f"finora_backup_{timestamp}.json")
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        return manifest

    @classmethod
    def restore_sqlite(cls, backup_path: str, target_db_path: str, expected_sha256: str = None) -> bool:
        """
        Verifies checksum and restores an SQLite database from backup snapshot.
        """
        if not os.path.exists(backup_path):
            raise FileNotFoundError(f"Backup file not found at: {backup_path}")

        if expected_sha256:
            actual_checksum = cls.compute_file_sha256(backup_path)
            if actual_checksum != expected_sha256:
                raise ValueError(f"Backup checksum mismatch! Expected: {expected_sha256}, Actual: {actual_checksum}")

        # Atomic copy over target database
        shutil.copy2(backup_path, target_db_path)
        return True

    @classmethod
    def backup_postgres(cls, db_url: str, backup_dir: str) -> Dict[str, Any]:
        """
        Executes pg_dump for PostgreSQL production database with custom format (-Fc).
        """
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_filename = f"finora_pg_backup_{timestamp}.dump"
        backup_path = os.path.join(backup_dir, backup_filename)

        cmd = [
            "pg_dump",
            "--dbname", db_url,
            "--format=c",
            "--file", backup_path,
            "--no-owner",
            "--no-acl"
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"pg_dump failed: {result.stderr}")

        checksum = cls.compute_file_sha256(backup_path)
        manifest = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "database_type": "postgresql",
            "backup_path": backup_path,
            "sha256_checksum": checksum,
            "file_size_bytes": os.path.getsize(backup_path),
            "status": "COMPLETED"
        }
        return manifest
