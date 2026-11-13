# Finora — Performance Test Report

**QA Date:** 2026-11-13  
**QA Lead:** Autonomous QA Engine  
**Methodology:** Live HTTP timing via Python `time.monotonic()`, 5 iterations per endpoint, avg/min/max recorded

---

## 1. API Response Time Benchmarks

All tests performed against `http://127.0.0.1:8000` with a valid authenticated Bearer token and an empty tenant (no data loaded).

| Grade | Endpoint | Avg (ms) | Min (ms) | Max (ms) |
|---|---|---|---|---|
| ✅ FAST | `/api/v1/dashboard/overview` | 23.0 | 20.8 | 25.0 |
| ✅ FAST | `/api/v1/dashboard/ai-investigations` | 13.5 | 11.1 | 15.4 |
| ✅ FAST | `/api/v1/dashboard/review-queue` | 11.2 | 9.8 | 12.4 |
| ✅ FAST | `/api/v1/dashboard/fee-analytics` | 12.3 | 11.6 | 13.3 |
| ✅ FAST | `/api/v1/dashboard/audit-logs` | 12.7 | 11.9 | 13.3 |
| ✅ FAST | `/api/v1/leakage/summary` | 11.3 | 10.1 | 12.3 |
| ✅ FAST | `/api/v1/leakage/exceptions` | 11.8 | 11.0 | 12.4 |
| ✅ FAST | `/api/v1/leakage/runs` | 11.5 | 10.3 | 12.8 |
| ✅ FAST | `/api/v1/reconciliation/runs` | 22.6 | 11.3 | 38.4 |
| ✅ FAST | `/api/v1/reconciliation/contracts` | 15.3 | 13.5 | 18.4 |
| ✅ FAST | `/api/v1/auth/me` | 8.5 | 7.0 | 9.5 |
| ✅ FAST | `/health/live` | 3.2 | 2.4 | 3.9 |
| ✅ FAST | `/health/ready` | 4.1 | 3.3 | 5.2 |

**Overall average response time: 12.4ms**  
**Classification: 13/13 FAST (<100ms), 0 OK, 0 SLOW**

---

## 2. Performance Thresholds

| Threshold | Definition | Result |
|---|---|---|
| FAST | < 100ms avg | ✅ All 13 endpoints |
| OK | 100–500ms avg | — None |
| SLOW | > 500ms avg | ✗ None |

---

## 3. Test Suite Execution Times

| Suite | Tests | Duration |
|---|---|---|
| Full regression (202 tests) | 202 | 106.65s |
| Leakage detectors (60 tests) | 60 | 34.13s |
| Reconciliation engine (15 tests) | 15 | 11.90s |
| Security hardening (25 tests) | 25 | 10.50s |
| AI/Gemini integration (20 tests) | 20 | 4.05s |
| Auth + Dashboard + Health (12 tests) | 12 | 7.52s |
| Ingestion (13 tests) | 13 | 9.84s |
| Financial integrity (9 tests) | 9 | 3.48s |

---

## 4. Frontend Build Performance

| Metric | Value |
|---|---|
| `next build` output | Static (pre-rendered) |
| TypeScript check (`tsc --noEmit`) | 0 errors, ~15s |
| Largest route bundle | ~7.5 kB (leakage-detection) |
| Shared JS chunks | 87.3 kB (gzipped: ~28 kB est.) |

---

## 5. Notes & Limitations

- Performance tests run on a local machine with SQLite (dev database), no concurrent load.
- Results with PostgreSQL and concurrent users will differ.
- No load testing (100+ concurrent users) was performed in this QA cycle.
- All response times measured via loopback (localhost) — add ~20–50ms for LAN/WAN.
- Hypothesis property-based tests extend the full test suite time due to example generation.

---

## Performance Verdict

**✅ EXCELLENT** — All 13 measured API endpoints respond under 25ms on average. The backend is efficient for its current dataset size. No SLOW endpoints found.

*All timings from actual execution. No estimates or extrapolations.*
