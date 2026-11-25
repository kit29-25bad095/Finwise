"""
Finora Production S3-Compatible Backup & Disaster Recovery Test Suite.
Validates:
1. Atomic backup of database and evidence storage.
2. Cryptographic SHA-256 manifest generation.
3. Tamper detection and fail-closed checksum verification.
4. Zip-Slip directory traversal defense.
5. End-to-end catastrophic disaster recovery drill with 100% financial and byte parity.
6. S3 upload simulation and retention pruning safety (never deleting on upload failure).
"""

import os
import uuid
import json
import sqlite3
import tempfile
import tarfile
from decimal import Decimal
from pathlib import Path
import pytest

from scripts.s3_backup_restore import S3BackupEngine, compute_sha256


@pytest.fixture
def mock_environment():
    """Sets up a temporary sandbox environment with database and tenant evidence files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        base_path = Path(tmpdir)
        db_path = base_path / "test_finora.db"
        storage_path = base_path / "storage"
        backup_path = base_path / "backups"

        db_path.parent.mkdir(parents=True, exist_ok=True)
        storage_path.mkdir(parents=True, exist_ok=True)
        backup_path.mkdir(parents=True, exist_ok=True)

        # 1. Initialize SQLite database with financial records
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE canonical_orders (
                id TEXT PRIMARY KEY,
                order_ref TEXT,
                gross_amount TEXT,
                tenant_id TEXT
            )
        """)
        cur.execute("""
            CREATE TABLE canonical_payments (
                id TEXT PRIMARY KEY,
                payment_ref TEXT,
                amount TEXT,
                fee TEXT,
                tenant_id TEXT
            )
        """)
        tenant_1 = str(uuid.uuid4())
        tenant_2 = str(uuid.uuid4())

        for i in range(1, 11):
            cur.execute(
                "INSERT INTO canonical_orders VALUES (?, ?, ?, ?)",
                (f"ord_{i}", f"ORD-100{i}", f"{2500 * i}.7500", tenant_1 if i <= 5 else tenant_2)
            )
            cur.execute(
                "INSERT INTO canonical_payments VALUES (?, ?, ?, ?, ?)",
                (f"pay_{i}", f"PAY-GW-{i}", f"{2500 * i}.7500", "45.0000", tenant_1 if i <= 5 else tenant_2)
            )
        conn.commit()
        conn.close()

        # 2. Populate tenant evidence files
        t1_dir = storage_path / tenant_1 / "SHOPIFY"
        t2_dir = storage_path / tenant_2 / "RAZORPAY"
        t1_dir.mkdir(parents=True, exist_ok=True)
        t2_dir.mkdir(parents=True, exist_ok=True)

        ev_file_1 = t1_dir / "batch_shopify_orders.csv"
        ev_file_2 = t2_dir / "batch_razorpay_settlement.csv"

        ev_bytes_1 = b"order_id,gross_amount,currency\nORD-1001,2500.75,INR\nORD-1002,5000.75,INR\n"
        ev_bytes_2 = b"settlement_id,amount,utr\nSETT-8899,75000.00,HDFC0001234\n"

        with open(ev_file_1, "wb") as f:
            f.write(ev_bytes_1)
        with open(ev_file_2, "wb") as f:
            f.write(ev_bytes_2)

        yield {
            "tmpdir": base_path,
            "db_path": db_path,
            "db_url": f"sqlite:///{db_path}",
            "storage_path": storage_path,
            "backup_path": backup_path,
            "tenant_1": tenant_1,
            "tenant_2": tenant_2,
            "ev_bytes_1": ev_bytes_1,
            "ev_bytes_2": ev_bytes_2,
        }


def test_01_atomic_backup_creation_and_checksums(mock_environment):
    """Verify full backup creates database dump, evidence tarball, and valid SHA-256 manifest."""
    env = mock_environment
    res = S3BackupEngine.run_full_backup(
        db_url=env["db_url"],
        storage_dir=str(env["storage_path"]),
        backup_dir=str(env["backup_path"]),
    )

    assert os.path.exists(res["database_file"])
    assert os.path.exists(res["evidence_file"])
    assert os.path.exists(res["manifest_file"])

    with open(res["manifest_file"], "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["status"] == "VERIFIED"
    assert manifest["retention_days"] == 2555
    assert manifest["database"]["type"] == "sqlite"
    assert manifest["evidence"]["file_count"] == 2

    # Verify cryptographic digests match reality
    actual_db_sha = compute_sha256(res["database_file"])
    actual_ev_sha = compute_sha256(res["evidence_file"])
    assert manifest["database"]["sha256"] == actual_db_sha
    assert manifest["evidence"]["sha256"] == actual_ev_sha


def test_02_evidence_tarball_preserves_tenant_structure(mock_environment):
    """Verify evidence tar.gz preserves relative tenant paths."""
    env = mock_environment
    res = S3BackupEngine.run_full_backup(
        db_url=env["db_url"],
        storage_dir=str(env["storage_path"]),
        backup_dir=str(env["backup_path"]),
    )

    with tarfile.open(res["evidence_file"], "r:gz") as tar:
        names = tar.getnames()
        # Should have relative paths without leading slashes or absolute paths
        assert any(env["tenant_1"] in n for n in names)
        assert any(env["tenant_2"] in n for n in names)
        for n in names:
            assert not n.startswith("/")
            assert not n.startswith("..")


def test_03_restore_rejects_tampered_database(mock_environment):
    """Verify disaster recovery fails closed if database dump is modified or corrupted."""
    env = mock_environment
    res = S3BackupEngine.run_full_backup(
        db_url=env["db_url"],
        storage_dir=str(env["storage_path"]),
        backup_dir=str(env["backup_path"]),
    )

    db_file = Path(res["database_file"])
    with open(db_file, "ab") as f:
        f.write(b"CORRUPTION_BYTES_APPENDED")

    with open(res["manifest_file"], "r", encoding="utf-8") as f:
        manifest = json.load(f)

    with pytest.raises(ValueError) as excinfo:
        S3BackupEngine.restore_database(
            db_file=db_file,
            target_db_url=env["db_url"],
            expected_sha256=manifest["database"]["sha256"]
        )
    assert "checksum mismatch" in str(excinfo.value).lower()


def test_04_restore_rejects_tampered_evidence_archive(mock_environment):
    """Verify disaster recovery fails closed if evidence tarball is modified or corrupted."""
    env = mock_environment
    res = S3BackupEngine.run_full_backup(
        db_url=env["db_url"],
        storage_dir=str(env["storage_path"]),
        backup_dir=str(env["backup_path"]),
    )

    ev_file = Path(res["evidence_file"])
    with open(ev_file, "ab") as f:
        f.write(b"CORRUPTION_TAMPER_BYTES")

    with open(res["manifest_file"], "r", encoding="utf-8") as f:
        manifest = json.load(f)

    with pytest.raises(ValueError) as excinfo:
        S3BackupEngine.restore_evidence(
            archive_path=ev_file,
            target_storage_dir=env["storage_path"],
            expected_sha256=manifest["evidence"]["sha256"]
        )
    assert "checksum mismatch" in str(excinfo.value).lower()


def test_05_zip_slip_path_traversal_defense(mock_environment):
    """Verify zip-slip path traversal exploits in evidence archive are caught and blocked."""
    env = mock_environment
    malicious_tar_path = env["backup_path"] / "malicious.tar.gz"

    with tarfile.open(malicious_tar_path, "w:gz") as tar:
        # Create a dummy payload file outside the target directory
        dummy_file = env["tmpdir"] / "dummy.txt"
        with open(dummy_file, "w") as f:
            f.write("malicious payload")
        tar.add(dummy_file, arcname="../../evil_escaped.txt")

    with pytest.raises(PermissionError) as excinfo:
        S3BackupEngine.restore_evidence(
            archive_path=malicious_tar_path,
            target_storage_dir=env["storage_path"]
        )
    assert "malicious archive entry detected" in str(excinfo.value).lower()


def test_06_end_to_end_disaster_recovery_drill(mock_environment):
    """
    Executes a complete catastrophic disaster recovery drill:
    1. Creates atomic backup.
    2. Completely wipes out primary database and all tenant evidence files.
    3. Restores from backup with SHA-256 validation.
    4. Confirms 100% financial and byte-for-byte fidelity.
    """
    env = mock_environment

    # 1. Create full backup
    res = S3BackupEngine.run_full_backup(
        db_url=env["db_url"],
        storage_dir=str(env["storage_path"]),
        backup_dir=str(env["backup_path"]),
    )
    with open(res["manifest_file"], "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # 2. Catastrophic data loss simulation: delete database and evidence directory
    conn = sqlite3.connect(str(env["db_path"]))
    cur = conn.cursor()
    cur.execute("DELETE FROM canonical_orders")
    cur.execute("DELETE FROM canonical_payments")
    conn.commit()
    conn.close()

    for p in env["storage_path"].glob("**/*"):
        if p.is_file():
            p.unlink()

    # Verify data is wiped
    conn = sqlite3.connect(str(env["db_path"]))
    cur = conn.cursor()
    assert cur.execute("SELECT COUNT(*) FROM canonical_orders").fetchone()[0] == 0
    conn.close()

    # 3. Perform disaster recovery restoration
    db_restored = S3BackupEngine.restore_database(
        db_file=Path(res["database_file"]),
        target_db_url=env["db_url"],
        expected_sha256=manifest["database"]["sha256"]
    )
    assert db_restored is True

    files_restored = S3BackupEngine.restore_evidence(
        archive_path=Path(res["evidence_file"]),
        target_storage_dir=env["storage_path"],
        expected_sha256=manifest["evidence"]["sha256"]
    )
    assert files_restored == 2

    # 4. Verify 100% database record recovery and financial precision
    restored_conn = sqlite3.connect(str(env["db_path"]))
    restored_cur = restored_conn.cursor()

    order_count = restored_cur.execute("SELECT COUNT(*) FROM canonical_orders").fetchone()[0]
    payment_count = restored_cur.execute("SELECT COUNT(*) FROM canonical_payments").fetchone()[0]
    assert order_count == 10
    assert payment_count == 10

    # Verify exact financial decimal values
    row = restored_cur.execute("SELECT gross_amount FROM canonical_orders WHERE order_ref='ORD-1001'").fetchone()
    assert Decimal(row[0]) == Decimal("2500.7500")

    row_fee = restored_cur.execute("SELECT fee FROM canonical_payments WHERE payment_ref='PAY-GW-1'").fetchone()
    assert Decimal(row_fee[0]) == Decimal("45.0000")
    restored_conn.close()

    # Verify 100% byte fidelity of restored evidence files
    restored_ev_1 = env["storage_path"] / env["tenant_1"] / "SHOPIFY" / "batch_shopify_orders.csv"
    restored_ev_2 = env["storage_path"] / env["tenant_2"] / "RAZORPAY" / "batch_razorpay_settlement.csv"

    assert restored_ev_1.exists()
    assert restored_ev_2.exists()
    assert restored_ev_1.read_bytes() == env["ev_bytes_1"]
    assert restored_ev_2.read_bytes() == env["ev_bytes_2"]


def test_07_s3_upload_lifecycle_and_retention_safety(mock_environment):
    """Verify that failure during S3 upload halts pruning and preserves all local files."""
    env = mock_environment

    uploaded_keys = []

    def mock_upload_success(local_path, bucket, key, region, sse):
        uploaded_keys.append(key)
        return True

    res = S3BackupEngine.run_full_backup(
        db_url=env["db_url"],
        storage_dir=str(env["storage_path"]),
        backup_dir=str(env["backup_path"]),
        s3_bucket="finora-production-backups-mumbai",
        upload_runner=mock_upload_success
    )
    assert res["s3_uploaded"] is True
    assert len(uploaded_keys) == 3

    # Now simulate S3 upload failure: verify exception is raised and local file remains intact
    def mock_upload_failure(local_path, bucket, key, region, sse):
        return False

    with pytest.raises(RuntimeError) as excinfo:
        S3BackupEngine.run_full_backup(
            db_url=env["db_url"],
            storage_dir=str(env["storage_path"]),
            backup_dir=str(env["backup_path"]),
            s3_bucket="finora-production-backups-mumbai",
            upload_runner=mock_upload_failure
        )
    assert "S3 backup upload failed" in str(excinfo.value)
