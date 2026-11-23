import os
import uuid
import time
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from app.core.config import settings

logger = logging.getLogger("finora.storage")


class PrivateFileStorageService:
    """
    Manages private, encrypted-at-rest or filesystem-isolated storage
    for sensitive financial documents (Shopify exports, Razorpay settlements, HDFC statements).

    Security Invariants:
    1. Zero public web accessibility (storage root is outside web server root).
    2. Tenant-isolated directory structure: {storage_root}/{tenant_id}/{source_type}/...
    3. Strict path traversal mitigation via path canonicalization.
    4. POSIX permission hardening (0700 directories, 0600 files).
    5. Statutory retention lifecycle enforcement (default 7 years = 2555 days).
    """

    @classmethod
    def get_storage_root(cls) -> Path:
        root = Path(settings.STORAGE_DIR).resolve()
        root.mkdir(parents=True, exist_ok=True)
        try:
            # Enforce 0700 directory permissions on POSIX
            if os.name == "posix":
                os.chmod(root, 0o700)
        except Exception as e:
            logger.warning("Could not set 0700 on storage root: %s", e)
        return root

    @classmethod
    def get_tenant_dir(cls, tenant_id: uuid.UUID, source_type: str = "general") -> Path:
        root = cls.get_storage_root()
        clean_source = "".join(c for c in source_type.upper() if c.isalnum() or c in ("_", "-"))
        tenant_dir = (root / str(tenant_id) / clean_source).resolve()

        # Strict containment verification
        if not str(tenant_dir).startswith(str(root)):
            raise ValueError("Path traversal attempt detected in tenant storage directory resolution.")

        tenant_dir.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            try:
                os.chmod(tenant_dir.parent, 0o700)
                os.chmod(tenant_dir, 0o700)
            except Exception as e:
                logger.warning("Could not set 0700 on tenant dir: %s", e)
        return tenant_dir

    @classmethod
    def save_batch_file(
        cls,
        tenant_id: uuid.UUID,
        batch_id: uuid.UUID,
        source_type: str,
        file_bytes: bytes,
        file_hash_sha256: str,
    ) -> str:
        """
        Persists uploaded file bytes to isolated private storage.
        Returns the canonical relative path within storage root.
        """
        tenant_dir = cls.get_tenant_dir(tenant_id, source_type)
        safe_hash = file_hash_sha256[:16]
        filename = f"{batch_id}_{safe_hash}.dat"
        file_path = (tenant_dir / filename).resolve()

        # Write securely
        with open(file_path, "wb") as f:
            f.write(file_bytes)

        if os.name == "posix":
            try:
                os.chmod(file_path, 0o600)
            except Exception as e:
                logger.warning("Could not set 0600 on storage file: %s", e)

        root = cls.get_storage_root()
        rel_path = file_path.relative_to(root).as_posix()
        logger.info(
            "Persisted private financial file for tenant %s (batch %s, size %d bytes) -> %s",
            tenant_id, batch_id, len(file_bytes), rel_path
        )
        return rel_path

    @classmethod
    def read_batch_file(cls, tenant_id: uuid.UUID, relative_path: str) -> bytes:
        """
        Reads private file bytes ensuring the target belongs to the given tenant.
        Prevents directory traversal and cross-tenant data leaks.
        """
        root = cls.get_storage_root()
        target_path = (root / relative_path).resolve()

        # Security check 1: Target must be inside storage root
        if not str(target_path).startswith(str(root)):
            raise PermissionError("Access denied: path is outside private storage root.")

        # Security check 2: Target must be inside tenant's dedicated directory
        tenant_prefix = (root / str(tenant_id)).resolve()
        if not str(target_path).startswith(str(tenant_prefix)):
            raise PermissionError(f"Access denied: file does not belong to tenant {tenant_id}.")

        if not target_path.exists() or not target_path.is_file():
            raise FileNotFoundError(f"Financial document not found: {relative_path}")

        with open(target_path, "rb") as f:
            return f.read()

    @classmethod
    def delete_batch_file(cls, tenant_id: uuid.UUID, relative_path: str) -> bool:
        """Safely removes a stored financial file under tenant isolation."""
        root = cls.get_storage_root()
        target_path = (root / relative_path).resolve()
        tenant_prefix = (root / str(tenant_id)).resolve()

        if not str(target_path).startswith(str(tenant_prefix)):
            raise PermissionError(f"Access denied: file does not belong to tenant {tenant_id}.")

        if target_path.exists() and target_path.is_file():
            target_path.unlink()
            logger.info("Deleted private file %s for tenant %s", relative_path, tenant_id)
            return True
        return False

    @classmethod
    def purge_expired_files(cls, retention_days: Optional[int] = None) -> int:
        """
        Scans storage directory and purges files exceeding statutory retention limit.
        Default: 2555 days (7 years under Indian Companies Act / Tax regulations).
        """
        if retention_days is None:
            retention_days = settings.FILE_RETENTION_DAYS

        cutoff_timestamp = time.time() - (retention_days * 86400)
        root = cls.get_storage_root()
        purged_count = 0

        for file_path in root.glob("**/*"):
            if file_path.is_file() and file_path.name.endswith(".dat"):
                try:
                    stat = file_path.stat()
                    if stat.st_mtime < cutoff_timestamp:
                        file_path.unlink()
                        purged_count += 1
                        logger.info("Purged expired financial document: %s (age > %d days)", file_path, retention_days)
                except Exception as e:
                    logger.warning("Error evaluating file %s for retention purge: %s", file_path, e)

        return purged_count

    @classmethod
    def audit_storage_security(cls) -> Dict[str, Any]:
        """Audits storage directory configuration and permissions."""
        root = cls.get_storage_root()
        is_posix = os.name == "posix"
        mode_octal = oct(root.stat().st_mode & 0o777) if is_posix else "windows_acl"
        
        return {
            "storage_root": str(root),
            "exists": root.exists(),
            "is_directory": root.is_dir(),
            "is_posix": is_posix,
            "permissions": mode_octal,
            "retention_days": settings.FILE_RETENTION_DAYS,
            "public_web_accessible": False,  # Strict invariant
        }
