import io
import uuid
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import CanonicalPayment, CanonicalSettlement

RAZORPAY_PAYMENTS_CSV = """payment_id,order_id,created_at,amount,fee,tax,method,card_network,card_type,status
pay_Oz91M202Kaa,order_Oz91M202Kaa,2026-11-10 10:30:00,15400.00,284.90,51.28,upi,,,captured
pay_Oz91M203Nba,order_Oz91M203Nba,2026-11-10 11:15:00,12500.00,231.25,41.63,card,Visa,consumer,captured
pay_Oz91M204Kpq,order_Oz91M204Kpq,2026-11-10 12:00:00,8400.00,180.60,32.51,card,Mastercard,corporate,captured
"""

RAZORPAY_SETTLEMENTS_CSV = """settlement_id,utr,created_at,amount,fee,tax
SETL-20261110-09,HDFCR5202611110098,2026-11-11 11:30:00,1250000.00,28450.00,5121.00
SETL-20261111-01,HDFCR5202611110099,2026-11-11 17:45:00,890000.00,19800.00,3564.00
"""

RAZORPAY_DUPLICATE_ROWS_CSV = """payment_id,order_id,created_at,amount,fee,tax,status
pay_DUP_001,order_001,2026-11-10 10:00:00,5000.00,100.00,18.00,captured
pay_DUP_001,order_001,2026-11-10 10:00:00,5000.00,100.00,18.00,captured
"""


def test_upload_valid_razorpay_payments(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]

    response = client.post(
        "/api/v1/ingestion/upload",
        headers=headers,
        data={"source_type": "RAZORPAY"},
        files={"file": ("razorpay_payments.csv", io.BytesIO(RAZORPAY_PAYMENTS_CSV.encode("utf-8")), "text/csv")}
    )
    assert response.status_code == 201
    batch_id = response.json()["id"]

    batch = db_session.get(IngestionBatch, uuid.UUID(batch_id))
    assert batch.status == IngestionStatus.COMPLETED
    assert batch.valid_rows == 3

    # Verify CanonicalPayment rows
    payments = db_session.execute(
        select(CanonicalPayment).where(CanonicalPayment.batch_id == batch.id).order_by(CanonicalPayment.source_row_index)
    ).scalars().all()
    assert len(payments) == 3
    assert payments[0].gateway_payment_id == "pay_Oz91M202Kaa"
    assert payments[0].captured_amount == Decimal("15400.0000")
    assert payments[0].reported_fee == Decimal("284.9000")
    assert payments[0].reported_tax == Decimal("51.2800")
    assert payments[0].payment_method == "upi"
    assert payments[1].card_network == "Visa"
    assert payments[2].card_type == "corporate"

    # Verify query endpoint
    list_resp = client.get("/api/v1/ingestion/canonical/payments", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 3


def test_upload_valid_razorpay_settlements(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]

    response = client.post(
        "/api/v1/ingestion/upload",
        headers=headers,
        data={"source_type": "RAZORPAY"},
        files={"file": ("razorpay_settlements.csv", io.BytesIO(RAZORPAY_SETTLEMENTS_CSV.encode("utf-8")), "text/csv")}
    )
    assert response.status_code == 201
    batch_id = response.json()["id"]

    batch = db_session.get(IngestionBatch, uuid.UUID(batch_id))
    assert batch.status == IngestionStatus.COMPLETED
    assert batch.valid_rows == 2

    settlements = db_session.execute(
        select(CanonicalSettlement).where(CanonicalSettlement.batch_id == batch.id).order_by(CanonicalSettlement.source_row_index)
    ).scalars().all()
    assert len(settlements) == 2
    assert settlements[0].settlement_reference == "SETL-20261110-09"
    assert settlements[0].utr_number == "HDFCR5202611110098"
    assert settlements[0].gross_amount == Decimal("1250000.0000")
    expected_net = Decimal("1250000.0000") - (Decimal("28450.0000") + Decimal("5121.0000"))
    assert settlements[0].net_settlement_amount == expected_net


def test_razorpay_duplicate_payment_id_isolated(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]

    response = client.post(
        "/api/v1/ingestion/upload",
        headers=headers,
        data={"source_type": "RAZORPAY"},
        files={"file": ("razorpay_duplicates.csv", io.BytesIO(RAZORPAY_DUPLICATE_ROWS_CSV.encode("utf-8")), "text/csv")}
    )
    assert response.status_code == 201
    batch_id = response.json()["id"]

    batch = db_session.get(IngestionBatch, uuid.UUID(batch_id))
    assert batch.status == IngestionStatus.COMPLETED_WITH_WARNINGS
    assert batch.total_rows == 2
    assert batch.valid_rows == 1  # First occurrence succeeds
    assert batch.duplicate_rows == 1  # Second occurrence isolated

    err_resp = client.get(f"/api/v1/ingestion/batches/{batch_id}/errors", headers=headers)
    assert err_resp.status_code == 200
    errors = err_resp.json()["errors"]
    assert len(errors) == 1
    assert errors[0]["error_code"] == "DUPLICATE_TRANSACTION_KEY"
    assert errors[0]["error_level"] == "DUPLICATE"
