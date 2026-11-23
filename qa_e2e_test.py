"""QA E2E API Test Script v2 for Finora"""
import urllib.request, json, http.client, urllib.parse

base = 'http://127.0.0.1:8000'
results = []

def api(method, path, data=None, headers=None):
    hdrs = dict(headers or {})
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        hdrs['Content-Type'] = 'application/json'
    r = urllib.request.Request(base + path, data=body, headers=hdrs, method=method)
    try:
        resp = urllib.request.urlopen(r)
        try:
            return json.load(resp), resp.status
        except Exception:
            return {}, resp.status
    except urllib.error.HTTPError as e:
        body2 = e.read().decode()
        return {'_error': e.code, '_body': body2[:200]}, e.code

def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    results.append((name, status, str(detail)[:80]))
    print("  {} | {} | {}".format(status, name, str(detail)[:80]))
    return cond

print("=" * 70)
print("FINORA QA — E2E API TESTS")
print("=" * 70)

# 1. REGISTER (new unique email each run)
import time
ts = str(int(time.time()))[-5:]
email = "qatest" + ts + "@example.com"
d, s = api('POST', '/api/v1/auth/register', {
    'email': email, 'password': 'QAPass@9876!',
    'full_name': 'QA Tester', 'tenant_name': 'QA Corp ' + ts, 'tenant_slug': 'qa-corp-' + ts
})
check('REGISTER', s == 201, "status={}".format(s))
token_from_reg = d.get('access_token', '')

# 2. LOGIN
d2, s2 = api('POST', '/api/v1/auth/login', {'email': email, 'password': 'QAPass@9876!'})
token = d2.get('access_token', token_from_reg)
check('LOGIN_TOKEN', bool(token), "status={}".format(s2))

auth = {'Authorization': 'Bearer ' + token}

# 3. AUTH/ME
d3, s3 = api('GET', '/api/v1/auth/me', headers=auth)
check('AUTH_ME', d3.get('email') == email, "email={}".format(d3.get('email')))

# 4. DASHBOARD OVERVIEW
d4, s4 = api('GET', '/api/v1/dashboard/overview', headers=auth)
check('DASHBOARD_OVERVIEW', s4 == 200 and isinstance(d4, dict), "keys={}".format(list(d4.keys())[:6]))

# 5. AI INVESTIGATIONS - must show PENDING_CONFIGURATION not 500
d5, s5 = api('GET', '/api/v1/dashboard/ai-investigations', headers=auth)
ai_ok = s5 == 200 and d5.get('status') == 'PENDING_CONFIGURATION'
check('AI_INVESTIGATIONS_PENDING', ai_ok, "status={} ai_status={}".format(s5, d5.get('status')))

# 6. LEAKAGE SUMMARY - must return 200 not 500
d6, s6 = api('GET', '/api/v1/leakage/summary', headers=auth)
check('LEAKAGE_SUMMARY', s6 == 200, "status={}".format(s6))

# 7. RECON RUNS (empty)
d7, s7 = api('GET', '/api/v1/reconciliation/runs', headers=auth)
check('RECON_RUNS_EMPTY', s7 == 200 and isinstance(d7, list), "count={}".format(len(d7) if isinstance(d7, list) else d7))

# 8. REVIEW QUEUE
d8, s8 = api('GET', '/api/v1/dashboard/review-queue', headers=auth)
check('REVIEW_QUEUE', s8 == 200, "status={}".format(s8))

# 9. FEE ANALYTICS
d9, s9 = api('GET', '/api/v1/dashboard/fee-analytics', headers=auth)
check('FEE_ANALYTICS', s9 == 200, "status={}".format(s9))

# 10. AUDIT LOGS
d10, s10 = api('GET', '/api/v1/dashboard/audit-logs', headers=auth)
check('AUDIT_LOGS', s10 == 200, "status={}".format(s10))

# 11. BAD JWT
d11, s11 = api('GET', '/api/v1/dashboard/overview', headers={'Authorization': 'Bearer bad.jwt.token'})
check('BAD_JWT_REJECTED', s11 == 401, "got={}".format(s11))

# 12. NO AUTH
d12, s12 = api('GET', '/api/v1/dashboard/overview')
check('NO_AUTH_REJECTED', s12 in [401, 403], "got={}".format(s12))

# 13. WRONG PASSWORD REJECTED
d13, s13 = api('POST', '/api/v1/auth/login', {'email': email, 'password': 'WrongPassword!'})
check('WRONG_PASS_REJECTED', s13 == 401, "got={}".format(s13))

# 14. SQL INJECTION IN PARAM (URL-encoded)
sql_param = urllib.parse.urlencode({'search': "' OR 1=1--"})
d14, s14 = api('GET', '/api/v1/leakage/exceptions?' + sql_param, headers=auth)
check('SQL_INJECTION_SAFE', s14 in [200, 400, 422], "got={}".format(s14))

# 15. OWASP HEADERS
conn = http.client.HTTPConnection('127.0.0.1', 8000)
conn.request('GET', '/api/v1/dashboard/overview', headers={'Authorization': 'Bearer ' + token})
raw = conn.getresponse()
hdrs = {k.lower(): v for k,v in raw.getheaders()}
raw.read()  # drain
owasp = {
    'x-frame-options': hdrs.get('x-frame-options', 'MISSING'),
    'x-content-type-options': hdrs.get('x-content-type-options', 'MISSING'),
    'csp': 'PRESENT' if 'content-security-policy' in hdrs else 'MISSING'
}
check('OWASP_HEADERS', 'MISSING' not in owasp.values(), str(owasp))

# 16. DUPLICATE EMAIL REGISTRATION REJECTED
d16, s16 = api('POST', '/api/v1/auth/register', {
    'email': email, 'password': 'AnotherPass@1!',
    'full_name': 'Duplicate', 'tenant_name': 'Dup Corp', 'tenant_slug': 'dup-corp-' + ts
})
check('DUPLICATE_EMAIL_REJECTED', s16 in [400, 409, 422], "got={}".format(s16))

# 17. LEAKAGE EXCEPTIONS LIST
d17, s17 = api('GET', '/api/v1/leakage/exceptions', headers=auth)
check('LEAKAGE_EXCEPTIONS_LIST', s17 == 200, "status={}".format(s17))

# 18. RECON CONTRACTS LIST (may be empty)
d18, s18 = api('GET', '/api/v1/reconciliation/contracts', headers=auth)
check('RECON_CONTRACTS', s18 == 200, "status={}".format(s18))

# 19. TENANTS ENDPOINT
d19, s19 = api('GET', '/api/v1/tenants/', headers=auth)
check('TENANTS_ENDPOINT', s19 in [200, 403], "status={}".format(s19))

# 20. LEAKAGE RUNS LIST
d20, s20 = api('GET', '/api/v1/leakage/runs', headers=auth)
check('LEAKAGE_RUNS', s20 == 200, "status={}".format(s20))

print()
print("=" * 70)
passed = sum(1 for _,s,_ in results if s == 'PASS')
failed = sum(1 for _,s,_ in results if s == 'FAIL')
print("TOTAL: {} PASSED / {} FAILED / {} TOTAL".format(passed, failed, len(results)))
print("=" * 70)
