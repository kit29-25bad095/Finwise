import io
import uuid
from decimal import Decimal
from datetime import date
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.models.ingestion import IngestionBatch, IngestionStatus
from app.models.canonical import CanonicalBankTransaction

HDFC_VALID_CSV = """Date,Narration,Chq/Ref No.,Value Dt,Withdrawal Amt.,Deposit Amt.,Closing Balance
10/11/2026,CMS/RZP/NODAL/SETL-20261110-09,,10/11/2026,,1221550.00,14820500.00
11/11/2026,RTGS CR-HDFCR5202611110099-RAZORPAY NODAL,HDFCR5202611110099,11/11/2026,,870200.00,15690700.00
11/11/2026,VENDOR PAYMENT-OFFICE SUPPLIES,CHQ000412,11/11/2026,45000.00,,15645700.00
12/11/2026,MONTHLY ACCOUNT MAINTENANCE CHARGE,CHQ000000,12/11/2026,590.00,,15645110.00
"""


def test_upload_valid_hdfc_bank_statement(client: TestClient, db_session: Session, seeded_entities: dict):
    headers = seeded_entities["headers_a_admin"]

    response = client.post(
        "/api/v1/ingestion/upload",
        headers=headers,
        data={"source_type": "HDFC"},
        files={"file": ("hdfc_statement_nov2026.csv", io.BytesIO(HDFC_VALID_CSV.encode("utf-8")), "text/csv")}
    )
    assert response.status_code == 201
    batch_id = response.json()["id"]

    batch = db_session.get(IngestionBatch, uuid.UUID(batch_id))
    assert batch.status == IngestionStatus.COMPLETED
    assert batch.valid_rows == 4
    assert batch.invalid_rows == 0

    txs = db_session.execute(
        select(CanonicalBankTransaction).where(CanonicalBankTransaction.batch_id == batch.id).order_by(CanonicalBankTransaction.source_row_index)
    ).scalars().all()
    assert len(txs) == 4

    # Verify UTR extraction from CMS narration
    assert txs[0].transaction_date == date(2026, 11, 10)
    assert txs[0].credit_amount == Decimal("1221550.0000")
    assert txs[0].extracted_utr == "CMS/RZP/NODAL/SETL-20261110-09"
    assert txs[0].running_balance == Decimal("14820500.0000")

    # Verify UTR extraction from Chq/Ref field
    assert txs[1].credit_amount == Decimal("870200.0000")
    assert txs[1].extracted_utr == "HDFCR5202611110099"

    # Verify debit withdrawal
    assert txs[2].debit_amount == Decimal("45000.0000")
    assert txs[2].credit_amount == Decimal("0.0000")

    # Verify canonical query endpoint
    list_resp = client.get("/api/v1/ingestion/canonical/bank-transactions", headers=headers)
    assert list_resp.status_code == 200
    assert len(list_resp.json()) == 4
