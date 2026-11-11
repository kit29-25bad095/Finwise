import os
import uuid
import pytest
from typing import Generator
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker

os.environ["ENVIRONMENT"] = "test"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SYNC_DATABASE_URL"] = "sqlite://"
os.environ["REDIS_URL"] = "redis://localhost:6379/1"
os.environ["WORKER_FALLBACK_SYNC"] = "true"

from app.core.config import settings
from app.core.database import Base, get_db_session
import app.core.database
from app.core.security import get_password_hash, create_access_token
from app.core.rbac import Role
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
import app.models  # ensure models are registered
from app.main import app as fastapi_app
import app.workers.ingestion_tasks

test_engine = create_engine(
    "sqlite://",
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

TestSessionLocal = sessionmaker(
    bind=test_engine,
    autocommit=False,
    autoflush=False
)

app.core.database.engine = test_engine
app.core.database.SessionLocal = TestSessionLocal
app.workers.ingestion_tasks.SessionLocal = TestSessionLocal


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(test_engine)
    Base.metadata.create_all(test_engine)
    yield
    Base.metadata.drop_all(test_engine)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client(db_session: Session) -> Generator[TestClient, None, None]:
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    fastapi_app.dependency_overrides[get_db_session] = override_get_db
    yield TestClient(fastapi_app)
    fastapi_app.dependency_overrides.clear()


@pytest.fixture
def seeded_entities(db_session: Session):
    tenant_a = Tenant(
        name="Alpha D2C Brands",
        slug="alpha-d2c",
        default_currency="INR"
    )
    tenant_b = Tenant(
        name="Beta Retailers",
        slug="beta-retail",
        default_currency="INR"
    )
    db_session.add_all([tenant_a, tenant_b])
    db_session.flush()

    pwd_hash = get_password_hash("Password123!")

    admin_a = User(
        email="admin@alpha.com",
        hashed_password=pwd_hash,
        full_name="Alpha Admin"
    )
    manager_a = User(
        email="manager@alpha.com",
        hashed_password=pwd_hash,
        full_name="Alpha Manager"
    )
    auditor_a = User(
        email="auditor@alpha.com",
        hashed_password=pwd_hash,
        full_name="Alpha Auditor"
    )
    admin_b = User(
        email="admin@beta.com",
        hashed_password=pwd_hash,
        full_name="Beta Admin"
    )
    db_session.add_all([admin_a, manager_a, auditor_a, admin_b])
    db_session.flush()

    mem_admin_a = TenantMembership(
        tenant_id=tenant_a.id,
        user_id=admin_a.id,
        role=Role.ADMIN.value,
        is_default=True
    )
    mem_manager_a = TenantMembership(
        tenant_id=tenant_a.id,
        user_id=manager_a.id,
        role=Role.FINANCE_MANAGER.value,
        is_default=True
    )
    mem_auditor_a = TenantMembership(
        tenant_id=tenant_a.id,
        user_id=auditor_a.id,
        role=Role.AUDITOR.value,
        is_default=True
    )
    mem_admin_b = TenantMembership(
        tenant_id=tenant_b.id,
        user_id=admin_b.id,
        role=Role.ADMIN.value,
        is_default=True
    )
    db_session.add_all([mem_admin_a, mem_manager_a, mem_auditor_a, mem_admin_b])
    db_session.commit()

    token_admin_a = create_access_token(admin_a.id, tenant_a.id, Role.ADMIN.value)
    token_manager_a = create_access_token(manager_a.id, tenant_a.id, Role.FINANCE_MANAGER.value)
    token_auditor_a = create_access_token(auditor_a.id, tenant_a.id, Role.AUDITOR.value)
    token_admin_b = create_access_token(admin_b.id, tenant_b.id, Role.ADMIN.value)

    return {
        "tenant_a": tenant_a,
        "tenant_b": tenant_b,
        "admin_a": admin_a,
        "manager_a": manager_a,
        "auditor_a": auditor_a,
        "admin_b": admin_b,
        "token_admin_a": token_admin_a,
        "token_manager_a": token_manager_a,
        "token_auditor_a": token_auditor_a,
        "token_admin_b": token_admin_b,
        "headers_a_admin": {"Authorization": f"Bearer {token_admin_a}"},
        "headers_a_manager": {"Authorization": f"Bearer {token_manager_a}"},
        "headers_a_auditor": {"Authorization": f"Bearer {token_auditor_a}"},
        "headers_b_admin": {"Authorization": f"Bearer {token_admin_b}"},
    }
