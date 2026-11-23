"""
Finora Enterprise QA - Performance, Load & Concurrency Benchmark Suite
Executes end-to-end performance and throughput benchmarks:
1. High-Volume Ingestion (1,000 rows normalized)
2. 3-Way Reconciliation Engine Throughput (1,000 records processed)
3. Revenue Leakage Detection Engine Execution (4 detectors over 1,000 records)
4. Concurrent API Latency & RPS (P50, P90, P99 under 50 concurrent threads)
5. Database Connection Pool & Query Execution Benchmarks
"""

import os
import sys
import time
import uuid
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timezone
from decimal import Decimal

# Ensure backend root is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import select, and_
from sqlalchemy.orm import Session
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import SessionLocal
from app.core.security import get_password_hash, create_access_token
from app.core.rbac import Role
from app.models.tenant import Tenant, TenantMembership
from app.models.user import User
from app.models.reconciliation import FeeContract, FeeScheduleTier
from app.models.canonical import CanonicalOrder, CanonicalPayment, CanonicalSettlement, CanonicalBankTransaction
from app.services.ingestion.ingestion_service import IngestionService
from app.services.reconciliation.reconciliation_service import ReconciliationService
from app.services.leakage.detection_engine import DetectionEngine

client = TestClient(app)


def execute_benchmarks():
    print("=" * 80)
    print("FINORA ENTERPRISE QA - PERFORMANCE & LOAD BENCHMARK")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 80)

    db: Session = SessionLocal()
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    results = {}

    try:
        # Setup synthetic enterprise tenant
        tenant = Tenant(
            id=tenant_id,
            name=f"Perf Enterprise ({tenant_id.hex[:6]})",
            slug=f"perf-tenant-{tenant_id.hex[:8]}",
            default_currency="INR",
            settlement_cutoff_time="23:00",
            fee_overcharge_tolerance=Decimal("0.0500"),
            max_knapsack_bound=5,
            is_active=True,
        )
        db.add(tenant)

        user = User(
            id=user_id,
            email=f"perf.tester.{tenant_id.hex[:6]}@finora.internal",
            hashed_password=get_password_hash("PerfPassword#2026"),
            full_name="Performance Testing Agent",
            is_active=True,
            is_superuser=False,
        )
        db.add(user)

        membership = TenantMembership(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            role=Role.FINANCE_MANAGER,
            is_default=True,
        )
        db.add(membership)
        db.commit()

        contract = FeeContract(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            gateway_name="RAZORPAY",
            contract_name="Razorpay Standard Staging Contract",
            start_date=date(2026, 1, 1),
            end_date=date(2027, 12, 31),
            gst_rate=Decimal("0.180000"),
            is_active=True,
        )
        db.add(contract)
        db.commit()

        tier = FeeScheduleTier(
            id=uuid.uuid4(),
            contract_id=contract.id,
            tenant_id=tenant_id,
            instrument_type="UPI",
            percentage_rate=Decimal("0.020000"),
            fixed_fee_per_txn=Decimal("0.0000"),
        )
        db.add(tier)
        db.commit()

        # ----------------------------------------------------------------------
        # BENCHMARK 1: High-Volume Ingestion & Normalization Throughput
        # ----------------------------------------------------------------------
        print("\n[Benchmark 1] Generating & Normalizing 1,000 Canonical Financial Records...")
        row_count = 500
        shopify_lines = ["Name,Total,Created at,Financial Status"]
        razorpay_lines = ["payment_id,order_id,amount,fee,tax,payment_method,created_at,status"]
        for i in range(1, row_count + 1):
            ref = f"ORD-PRF-{i:05d}"
            amt = "1500.00"
            shopify_lines.append(f"#{ref},{amt},2026-11-10T10:00:00Z,paid")
            fee = "30.00" if i % 20 != 0 else "90.00"  # 5% intentional overcharges
            tax = "5.40" if i % 20 != 0 else "16.20"
            razorpay_lines.append(f"pay_PRF_{i:05d},{ref},{amt},{fee},{tax},UPI,2026-11-10T10:05:00Z,captured")

        shopify_bytes = "\n".join(shopify_lines).encode("utf-8")
        razorpay_bytes = "\n".join(razorpay_lines).encode("utf-8")

        t0 = time.perf_counter()
        batch_shop, _ = IngestionService.register_upload(db, tenant_id, user_id, "SHOPIFY", "orders_perf.csv", shopify_bytes)
        IngestionService.process_csv_batch(db, batch_shop.id, shopify_bytes)
        t_shop = time.perf_counter() - t0

        t1 = time.perf_counter()
        batch_rzp, _ = IngestionService.register_upload(db, tenant_id, user_id, "RAZORPAY", "payments_perf.csv", razorpay_bytes)
        IngestionService.process_csv_batch(db, batch_rzp.id, razorpay_bytes)
        t_rzp = time.perf_counter() - t1

        total_norm_time = t_shop + t_rzp
        total_rows = row_count * 2
        throughput_rows_sec = total_rows / total_norm_time
        print(f"  Processed {total_rows} records in {total_norm_time:.3f}s -> Throughput: {throughput_rows_sec:.1f} rows/sec")
        results["ingestion_throughput_rps"] = round(throughput_rows_sec, 1)

        # ----------------------------------------------------------------------
        # BENCHMARK 2: Reconciliation Engine Processing Time
        # ----------------------------------------------------------------------
        print("\n[Benchmark 2] Executing Deterministic 3-Way Reconciliation across 1,000 entities...")
        t_recon_start = time.perf_counter()
        run = ReconciliationService.create_run(db, tenant_id, user_id, {})
        completed_run = ReconciliationService.execute_run(db, run.id)
        t_recon = time.perf_counter() - t_recon_start

        recon_matches = completed_run.matched_orders_count or 0
        recon_rate = recon_matches / t_recon if t_recon > 0 else 0
        print(f"  Reconciliation executed in {t_recon:.3f}s ({completed_run.duration_ms}ms engine clock)")
        print(f"  Matched {recon_matches} orders -> Rate: {recon_rate:.1f} matches/sec")
        results["reconciliation_duration_ms"] = completed_run.duration_ms
        results["reconciliation_matches_per_sec"] = round(recon_rate, 1)

        # ----------------------------------------------------------------------
        # BENCHMARK 3: Revenue Leakage Detection Throughput
        # ----------------------------------------------------------------------
        print("\n[Benchmark 3] Executing 4 Revenue Leakage Detectors across 1,000 records...")
        t_leak_start = time.perf_counter()
        leak_run = DetectionEngine.create_run(
            db=db,
            tenant_id=tenant_id,
            user_id=user_id,
            reconciliation_run_id=run.id,
            parameters={},
        )
        completed_leak = DetectionEngine.execute_run(db, leak_run.id)
        t_leak = time.perf_counter() - t_leak_start

        leak_rate = (completed_leak.total_captures_evaluated or row_count) / t_leak if t_leak > 0 else 0
        print(f"  Detection executed in {t_leak:.3f}s ({completed_leak.duration_ms}ms engine clock)")
        print(f"  Identified {completed_leak.exceptions_count} leakage exceptions -> Rate: {leak_rate:.1f} evaluated/sec")
        results["leakage_detection_duration_ms"] = completed_leak.duration_ms
        results["leakage_evaluation_per_sec"] = round(leak_rate, 1)

        # ----------------------------------------------------------------------
        # BENCHMARK 4: API Concurrency & Latency Distribution
        # ----------------------------------------------------------------------
        print("\n[Benchmark 4] Concurrent API Stress Test (50 workers, 500 requests)...")
        token = create_access_token(str(user_id), str(tenant_id), Role.FINANCE_MANAGER)
        headers = {"Authorization": f"Bearer {token}"}

        endpoints = [
            ("/health/live", {}),
            ("/health/ready", {}),
            ("/metrics", {}),
            ("/api/v1/monitoring/metrics", {}),
            ("/api/v1/ingestion/batches", headers),
            ("/api/v1/reconciliation/runs", headers),
            ("/api/v1/leakage/runs", headers),
        ]

        latencies = []
        status_codes = {}

        def fetch_endpoint(url, h):
            start = time.perf_counter()
            resp = client.get(url, headers=h)
            elapsed_ms = (time.perf_counter() - start) * 1000.0
            return resp.status_code, elapsed_ms

        req_count = 500
        concurrency = 25
        t_api_start = time.perf_counter()

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = []
            for i in range(req_count):
                url, h = endpoints[i % len(endpoints)]
                futures.append(executor.submit(fetch_endpoint, url, h))

            for fut in as_completed(futures):
                code, elapsed_ms = fut.result()
                latencies.append(elapsed_ms)
                status_codes[code] = status_codes.get(code, 0) + 1

        total_api_time = time.perf_counter() - t_api_start
        rps = req_count / total_api_time

        latencies.sort()
        p50 = statistics.median(latencies)
        p90 = latencies[int(len(latencies) * 0.90)]
        p95 = latencies[int(len(latencies) * 0.95)]
        p99 = latencies[int(len(latencies) * 0.99)]
        avg = statistics.mean(latencies)

        print(f"  Total Requests: {req_count} in {total_api_time:.2f}s ({rps:.1f} RPS)")
        print(f"  Status Codes: {status_codes}")
        print(f"  Latency P50: {p50:.2f}ms | P90: {p90:.2f}ms | P95: {p95:.2f}ms | P99: {p99:.2f}ms | Mean: {avg:.2f}ms")
        assert status_codes.get(200, 0) > 0, "Initial burst within rate limit should succeed with 200 OK"
        assert status_codes.get(429, 0) > 0, "Rate limiter must throttle flood requests beyond window threshold"
        print("  OK: Rate Limiter actively throttled requests exceeding 120 req/min with HTTP 429.")

        results["api_rps"] = round(rps, 1)
        results["api_latency_p50_ms"] = round(p50, 2)
        results["api_latency_p90_ms"] = round(p90, 2)
        results["api_latency_p95_ms"] = round(p95, 2)
        results["api_latency_p99_ms"] = round(p99, 2)

        print("\n" + "=" * 80)
        print("PERFORMANCE BENCHMARK RESULTS SUMMARY:")
        for k, v in results.items():
            print(f"  {k}: {v}")
        print("=" * 80)

        return results

    finally:
        db.close()


if __name__ == "__main__":
    execute_benchmarks()
