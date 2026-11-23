"""Performance Test for Finora API"""
import urllib.request, json, time, urllib.parse

base = 'http://127.0.0.1:8000'

# Register and login once
import random
ts = str(int(time.time()))
email = "perftest" + ts + "@example.com"

d, s = None, None
r = urllib.request.Request(base + '/api/v1/auth/register',
    data=json.dumps({'email': email, 'password': 'PerfTest@1234!',
        'full_name': 'Perf Tester', 'tenant_name': 'Perf Corp', 'tenant_slug': 'perf-corp-' + ts}).encode(),
    headers={'Content-Type': 'application/json'})
resp = urllib.request.urlopen(r)
d = json.load(resp)
token = d['access_token']
auth = {'Authorization': 'Bearer ' + token}

print("=" * 60)
print("FINORA QA — PERFORMANCE TESTS")
print("=" * 60)

endpoints = [
    ('GET', '/api/v1/dashboard/overview'),
    ('GET', '/api/v1/dashboard/ai-investigations'),
    ('GET', '/api/v1/dashboard/review-queue'),
    ('GET', '/api/v1/dashboard/fee-analytics'),
    ('GET', '/api/v1/dashboard/audit-logs'),
    ('GET', '/api/v1/leakage/summary'),
    ('GET', '/api/v1/leakage/exceptions'),
    ('GET', '/api/v1/leakage/runs'),
    ('GET', '/api/v1/reconciliation/runs'),
    ('GET', '/api/v1/reconciliation/contracts'),
    ('GET', '/api/v1/auth/me'),
    ('GET', '/health/live'),
    ('GET', '/health/ready'),
]

ITERATIONS = 5
print("\nEndpoint Response Times (avg of {} iterations):".format(ITERATIONS))
print("-" * 60)

results = []
for method, path in endpoints:
    times = []
    for _ in range(ITERATIONS):
        start = time.monotonic()
        req = urllib.request.Request(base + path, headers=auth, method=method)
        try:
            resp = urllib.request.urlopen(req)
            resp.read()
            elapsed = (time.monotonic() - start) * 1000
            times.append(elapsed)
        except Exception as e:
            times.append(9999)
    avg = sum(times) / len(times)
    mn = min(times)
    mx = max(times)
    grade = "FAST" if avg < 100 else ("OK" if avg < 500 else "SLOW")
    results.append((path, avg, mn, mx, grade))
    print("  {:4s} | {:45s} | avg={:7.1f}ms min={:6.1f}ms max={:6.1f}ms".format(grade, path[:45], avg, mn, mx))

print("-" * 60)
fast = sum(1 for _,avg,_,_,g in results if g == 'FAST')
ok = sum(1 for _,avg,_,_,g in results if g == 'OK')
slow = sum(1 for _,avg,_,_,g in results if g == 'SLOW')
overall_avg = sum(avg for _,avg,_,_,_ in results) / len(results)
print("FAST(< 100ms): {} | OK(< 500ms): {} | SLOW(>500ms): {}".format(fast, ok, slow))
print("Overall avg response time: {:.1f}ms".format(overall_avg))
print("=" * 60)
