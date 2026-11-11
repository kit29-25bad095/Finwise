import io
import uuid
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import CanonicalOrder

MALICIOUS_DDE_CSV = """Name,Created at,Financial Status,Total
=1+1,2026-11-10 10:00:00,paid,1000.00
@SUM(1;2),2026-11-10 11:00:00,paid,2000.00
+cmd|' /C calc'!A0,2026-11-10 12:00:00,paid,3000.00
-2+3*4,2026-11-10 13:00:00,paid,4000.00
"""


def test_csv_formula_injection_sanitization(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]

    response = client.post(
        "/api/v1/ingestion/upload",
        headers=headers,
        data={"source_type": "SHOPIFY"},
        files={"file": ("malicious_dde.csv", io.BytesIO(MALICIOUS_DDE_CSV.encode("utf-8")), "text/csv")}
    )
    assert response.status_code == 201
    batch_id = response.json()["id"]

    orders = db_session.execute(
        select(CanonicalOrder).where(CanonicalOrder.batch_id == uuid.UUID(batch_id)).order_by(CanonicalOrder.source_row_index)
    ).scalars().all()
    assert len(orders) == 4

    # Verify that formulas are escaped with a leading single quote or sanitized
    # =1+1 -> '=1+1
    # @SUM(1;2) -> '@SUM(1;2)
    for ord_item in orders:
        ref = ord_item.order_reference
        # Must not start directly with dangerous trigger character without being escaped
        assert not (ref.startswith("=") or ref.startswith("@") or ref.startswith("+") or ref.startswith("-") and len(ref) > 1 and not ref[1].isdigit())


def test_tenant_isolation_on_ingestion(client: TestClient, db_session: Session, seeded_entities: dict):
    headers_a = seeded_entities["headers_a_admin"]
    headers_b = seeded_entities["headers_b_admin"]

    # Upload file under Tenant A
    csv_content = "Name,Total\n#A-101,1000.00\n"
    resp_a = client.post(
        "/api/v1/ingestion/upload",
        headers=headers_a,
        data={"source_type": "SHOPIFY"},
        files={"file": ("tenant_a.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    )
    assert resp_a.status_code == 201
    batch_a_id = resp_a.json()["id"]

    # Tenant B attempts to retrieve Tenant A's batch
    resp_b_get = client.get(f"/api/v1/ingestion/batches/{batch_a_id}", headers=headers_b)
    assert resp_b_get.status_code == 404

    # Tenant B attempts to retrieve Tenant A's batch errors
    resp_b_err = client.get(f"/api/v1/ingestion/batches/{batch_a_id}/errors", headers=headers_b)
    assert resp_b_err.status_code == 404

    # Tenant B queries canonical orders -> must be empty for Tenant B
    resp_b_orders = client.get("/api/v1/ingestion/canonical/orders", headers=headers_b)
    assert resp_b_orders.status_code == 200
    assert len(resp_b_orders.json()) == 0


def test_rbac_auditor_cannot_upload_files(client: TestClient, seeded_entities: dict):
    headers_auditor = seeded_entities["headers_a_auditor"]

    csv_content = "Name,Total\n#AUDIT-1,1000.00\n"
    response = client.post(
        "/api/v1/ingestion/upload",
        headers=headers_auditor,
        data={"source_type": "SHOPIFY"},
        files={"file": ("audit.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
    )
    # Auditor does not have write permissions for uploads
    assert response.status_code == 403


def test_export_batch_errors_csv(client: TestClient, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]

    # Upload bad csv
    bad_csv = "Name,Total\n,INVALID_AMOUNT\n"
    up_resp = client.post(
        "/api/v1/ingestion/upload",
        headers=headers,
        data={"source_type": "SHOPIFY"},
        files={"file": ("bad_records.csv", io.BytesIO(bad_csv.encode("utf-8")), "text/csv")}
    )
    assert up_resp.status_code == 201
    batch_id = up_resp.json()["id"]

    # Download error report CSV
    export_resp = client.get(f"/api/v1/ingestion/batches/{batch_id}/errors/export", headers=headers)
    assert export_resp.status_code == 200
    assert "text/csv" in export_resp.headers["content-type"]
    content = export_resp.text
    assert "Row Number" in content
    assert "Error Code" in content
    assert "MISSING_ORDER_REFERENCE" in content


def test_cancel_ingestion_batch(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]

    # Create a batch in UPLOADED status manually
    tenant_id = seeded_entities["tenant_a"].id
    batch = IngestionBatch(
        tenant_id=tenant_id,
        source_type="SHOPIFY",
        filename="to_cancel.csv",
        file_hash_sha256="abc123cancelhash",
        status=IngestionStatus.UPLOADED,
    )
    db_session.add(batch)
    db_session.commit()
    db_session.refresh(batch)

    # Cancel batch
    cancel_resp = client.post(f"/api/v1/ingestion/batches/{batch.id}/cancel", headers=headers)
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == IngestionStatus.CANCELLED
