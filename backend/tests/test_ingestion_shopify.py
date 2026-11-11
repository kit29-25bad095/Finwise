import io
import uuid
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.ingestion import IngestionBatch, IngestionStatus, SourceRowError
from app.models.canonical import CanonicalOrder

SHOPIFY_VALID_CSV = """Name,Created at,Financial Status,Fulfillment Status,Currency,Subtotal,Shipping,Taxes,Total,Discount Amount,Payment Method
#1001,2026-11-10 10:30:00,paid,fulfilled,INR,12000.00,200.00,300.00,12500.00,0.00,Razorpay
#1002,2026-11-10 11:15:00,paid,fulfilled,INR,8000.00,100.00,300.00,8400.00,0.00,Razorpay
#1003,2026-11-10 12:00:00,pending,unfulfilled,INR,14000.00,0.00,200.00,14200.00,0.00,Razorpay
"""

SHOPIFY_WITH_ERRORS_CSV = """Name,Created at,Financial Status,Total
#2001,2026-11-10 10:00:00,paid,5000.00
,2026-11-10 11:00:00,paid,3000.00
#2003,2026-11-10 12:00:00,paid,INVALID_AMOUNT
"""

SHOPIFY_MISSING_HEADERS_CSV = """RandomHeader1,RandomHeader2
Value1,Value2
"""


def test_upload_valid_shopify_csv(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]

    response = client.post(
        "/api/v1/ingestion/upload",
        headers=headers,
        data={"source_type": "SHOPIFY"},
        files={"file": ("shopify_orders.csv", io.BytesIO(SHOPIFY_VALID_CSV.encode("utf-8")), "text/csv")}
    )
    assert response.status_code == 201
    data = response.json()
    assert data["source_type"] == "SHOPIFY"
    assert data["status"] in (IngestionStatus.COMPLETED, IngestionStatus.UPLOADED, IngestionStatus.PROCESSING)
    batch_id = data["id"]

    # Verify database persistence
    batch = db_session.get(IngestionBatch, uuid.UUID(batch_id))
    assert batch is not None
    assert batch.status == IngestionStatus.COMPLETED
    assert batch.valid_rows == 3
    assert batch.invalid_rows == 0
    assert batch.total_rows == 3

    # Verify canonical orders
    orders = db_session.execute(
        select(CanonicalOrder).where(CanonicalOrder.batch_id == batch.id).order_by(CanonicalOrder.source_row_index)
    ).scalars().all()
    assert len(orders) == 3
    assert orders[0].order_reference == "#1001"
    assert orders[0].order_number == "1001"
    assert orders[0].gross_amount == Decimal("12500.0000")
    assert orders[0].shipping_amount == Decimal("200.0000")
    assert orders[0].currency == "INR"


def test_shopify_missing_headers_fails(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]

    response = client.post(
        "/api/v1/ingestion/upload",
        headers=headers,
        data={"source_type": "SHOPIFY"},
        files={"file": ("shopify_bad_headers.csv", io.BytesIO(SHOPIFY_MISSING_HEADERS_CSV.encode("utf-8")), "text/csv")}
    )
    assert response.status_code == 201
    batch_id = response.json()["id"]

    batch = db_session.get(IngestionBatch, uuid.UUID(batch_id))
    assert batch.status == IngestionStatus.FAILED
    assert "Missing required headers" in batch.error_message


def test_shopify_isolated_row_errors(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]

    response = client.post(
        "/api/v1/ingestion/upload",
        headers=headers,
        data={"source_type": "SHOPIFY"},
        files={"file": ("shopify_partial_errors.csv", io.BytesIO(SHOPIFY_WITH_ERRORS_CSV.encode("utf-8")), "text/csv")}
    )
    assert response.status_code == 201
    batch_id = response.json()["id"]

    batch = db_session.get(IngestionBatch, uuid.UUID(batch_id))
    assert batch.status == IngestionStatus.COMPLETED_WITH_WARNINGS
    assert batch.total_rows == 3
    assert batch.valid_rows == 1  # #2001
    assert batch.invalid_rows == 2  # Row 2 (missing name) and Row 3 (invalid decimal)

    # Check errors endpoint
    err_resp = client.get(f"/api/v1/ingestion/batches/{batch_id}/errors", headers=headers)
    assert err_resp.status_code == 200
    err_data = err_resp.json()
    assert len(err_data["errors"]) == 2
    error_codes = [e["error_code"] for e in err_data["errors"]]
    assert "MISSING_ORDER_REFERENCE" in error_codes
    assert "INVALID_DECIMAL" in error_codes


def test_duplicate_file_upload_detection(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]

    # First upload
    resp1 = client.post(
        "/api/v1/ingestion/upload",
        headers=headers,
        data={"source_type": "SHOPIFY"},
        files={"file": ("shopify_dup.csv", io.BytesIO(SHOPIFY_VALID_CSV.encode("utf-8")), "text/csv")}
    )
    assert resp1.status_code == 201
    id1 = resp1.json()["id"]

    # Second upload with identical bytes
    resp2 = client.post(
        "/api/v1/ingestion/upload",
        headers=headers,
        data={"source_type": "SHOPIFY"},
        files={"file": ("shopify_dup_again.csv", io.BytesIO(SHOPIFY_VALID_CSV.encode("utf-8")), "text/csv")}
    )
    assert resp2.status_code == 201
    id2 = resp2.json()["id"]
    # Should identify as existing batch and not re-process
    assert id1 == id2
