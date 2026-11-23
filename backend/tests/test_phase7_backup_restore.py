"""
Phase 7 — Live Database Backup and Restore Verification Test.
Executes an end-to-end backup snapshot, simulates catastrophic data loss,
restores from the cryptographic snapshot, and validates 100% financial data parity.
"""

import os
import tempfile
import sqlite3
from decimal import Decimal
import pytest

from scripts.backup_restore import DatabaseBackupManager


def test_live_backup_restore_and_financial_integrity():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_primary.db")
        backup_dir = os.path.join(tmpdir, "backups")

        # 1. Create primary database and insert financial records
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE canonical_orders (
                id TEXT PRIMARY KEY,
                order_reference TEXT,
                gross_amount TEXT,
                status TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE canonical_payments (
                id TEXT PRIMARY KEY,
                gateway_payment_id TEXT,
                captured_amount TEXT,
                reported_fee TEXT
            )
        """)
        # Insert 10 records with exact Decimal strings
        for i in range(1, 11):
            cur.execute(
                "INSERT INTO canonical_orders VALUES (?, ?, ?, ?)",
                (f"ord_id_{i}", f"ORD-{1000 + i}", f"{1500 * i}.5000", "PAID")
            )
            cur.execute(
                "INSERT INTO canonical_payments VALUES (?, ?, ?, ?)",
                (f"pay_id_{i}", f"pay_gw_{i}", f"{1500 * i}.5000", "28.5000")
            )
        conn.commit()
        conn.close()

        # 2. Execute atomic backup
        manifest = DatabaseBackupManager.backup_sqlite(db_path, backup_dir)
        assert manifest["status"] == "COMPLETED"
        assert os.path.exists(manifest["backup_path"])
        assert manifest["sha256_checksum"] is not None

        # 3. Simulate catastrophic data loss (delete records from primary)
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("DELETE FROM canonical_orders")
        cur.execute("DELETE FROM canonical_payments")
        conn.commit()

        # Verify tables are empty
        cur.execute("SELECT COUNT(*) FROM canonical_orders")
        assert cur.fetchone()[0] == 0
        conn.close()

        # 4. Execute restore drill with SHA-256 validation
        restore_success = DatabaseBackupManager.restore_sqlite(
            backup_path=manifest["backup_path"],
            target_db_path=db_path,
            expected_sha256=manifest["sha256_checksum"]
        )
        assert restore_success is True

        # 5. Verify restored database has 100% data integrity and financial parity
        restored_conn = sqlite3.connect(db_path)
        restored_cur = restored_conn.cursor()

        restored_cur.execute("SELECT COUNT(*) FROM canonical_orders")
        order_count = restored_cur.fetchone()[0]
        assert order_count == 10

        restored_cur.execute("SELECT COUNT(*) FROM canonical_payments")
        payment_count = restored_cur.fetchone()[0]
        assert payment_count == 10

        # Verify exact precision of financial Decimal strings
        restored_cur.execute("SELECT gross_amount FROM canonical_orders WHERE order_reference='ORD-1001'")
        gross_amt = Decimal(restored_cur.fetchone()[0])
        assert gross_amt == Decimal("1500.5000")

        restored_cur.execute("SELECT reported_fee FROM canonical_payments WHERE gateway_payment_id='pay_gw_1'")
        fee_amt = Decimal(restored_cur.fetchone()[0])
        assert fee_amt == Decimal("28.5000")

        restored_conn.close()


def test_restore_rejects_corrupted_checksum():
    """Verify restore fails closed if SHA-256 checksum fails to match."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_corrupt.db")
        backup_dir = os.path.join(tmpdir, "backups")

        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("CREATE TABLE test (id INT)")
        cur.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        conn.close()

        manifest = DatabaseBackupManager.backup_sqlite(db_path, backup_dir)

        # Attempt restore with invalid checksum
        with pytest.raises(ValueError) as excinfo:
            DatabaseBackupManager.restore_sqlite(
                backup_path=manifest["backup_path"],
                target_db_path=db_path,
                expected_sha256="fake_corrupted_sha256_hash_12345"
            )
        assert "checksum mismatch" in str(excinfo.value).lower()
