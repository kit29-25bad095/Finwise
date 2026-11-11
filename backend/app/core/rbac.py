from enum import Enum
from typing import List, Set


class Role(str, Enum):
    ADMIN = "ADMIN"
    FINANCE_MANAGER = "FINANCE_MANAGER"
    AUDITOR = "AUDITOR"


# Permission constants
class Permission(str, Enum):
    # Tenant & User Management
    MANAGE_TENANT = "manage_tenant"
    MANAGE_USERS = "manage_users"
    VIEW_USERS = "view_users"

    # Data Ingestion
    UPLOAD_DATA = "upload_data"
    VIEW_UPLOADS = "view_uploads"

    # Reconciliation
    RUN_RECONCILIATION = "run_reconciliation"
    VIEW_RECONCILIATION = "view_reconciliation"

    # Exceptions & Claims
    REVIEW_EXCEPTIONS = "review_exceptions"
    APPROVE_CLAIMS = "approve_claims"
    EXPORT_CLAIMS = "export_claims"
    VIEW_EXCEPTIONS = "view_exceptions"

    # Contracts & Settings
    MANAGE_CONTRACTS = "manage_contracts"
    VIEW_CONTRACTS = "view_contracts"

    # Audit Logs
    VIEW_AUDIT_LOGS = "view_audit_logs"


ROLE_PERMISSIONS: dict[Role, Set[Permission]] = {
    Role.ADMIN: {
        Permission.MANAGE_TENANT,
        Permission.MANAGE_USERS,
        Permission.VIEW_USERS,
        Permission.UPLOAD_DATA,
        Permission.VIEW_UPLOADS,
        Permission.RUN_RECONCILIATION,
        Permission.VIEW_RECONCILIATION,
        Permission.REVIEW_EXCEPTIONS,
        Permission.APPROVE_CLAIMS,
        Permission.EXPORT_CLAIMS,
        Permission.VIEW_EXCEPTIONS,
        Permission.MANAGE_CONTRACTS,
        Permission.VIEW_CONTRACTS,
        Permission.VIEW_AUDIT_LOGS,
    },
    Role.FINANCE_MANAGER: {
        Permission.VIEW_USERS,
        Permission.UPLOAD_DATA,
        Permission.VIEW_UPLOADS,
        Permission.RUN_RECONCILIATION,
        Permission.VIEW_RECONCILIATION,
        Permission.REVIEW_EXCEPTIONS,
        Permission.APPROVE_CLAIMS,
        Permission.EXPORT_CLAIMS,
        Permission.VIEW_EXCEPTIONS,
        Permission.VIEW_CONTRACTS,
        Permission.VIEW_AUDIT_LOGS,
    },
    Role.AUDITOR: {
        Permission.VIEW_USERS,
        Permission.VIEW_UPLOADS,
        Permission.VIEW_RECONCILIATION,
        Permission.VIEW_EXCEPTIONS,
        Permission.VIEW_CONTRACTS,
        Permission.VIEW_AUDIT_LOGS,
    },
}


def has_permission(role: Role, permission: Permission) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())
