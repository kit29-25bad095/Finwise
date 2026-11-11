from fastapi.testclient import TestClient


def test_auditor_cannot_update_tenant_settings(client: TestClient, seeded_entities):
    token_auditor = seeded_entities["token_auditor_a"]
    tenant_a_id = str(seeded_entities["tenant_a"].id)

    headers = {"Authorization": f"Bearer {token_auditor}"}
    payload = {"settlement_cutoff_time": "19:00"}
    response = client.patch(f"/api/v1/tenants/{tenant_a_id}", json=payload, headers=headers)
    assert response.status_code == 403
    assert "requires one of the following roles: ADMIN" in response.json()["detail"]


def test_finance_manager_cannot_update_tenant_core_settings(client: TestClient, seeded_entities):
    token_manager = seeded_entities["token_manager_a"]
    tenant_a_id = str(seeded_entities["tenant_a"].id)

    headers = {"Authorization": f"Bearer {token_manager}"}
    payload = {"name": "New Alpha Name"}
    response = client.patch(f"/api/v1/tenants/{tenant_a_id}", json=payload, headers=headers)
    assert response.status_code == 403


def test_auditor_cannot_add_members(client: TestClient, seeded_entities):
    token_auditor = seeded_entities["token_auditor_a"]
    tenant_a_id = str(seeded_entities["tenant_a"].id)

    headers = {"Authorization": f"Bearer {token_auditor}"}
    payload = {"email": "someone@example.com", "role": "FINANCE_MANAGER"}
    response = client.post(f"/api/v1/tenants/{tenant_a_id}/members", json=payload, headers=headers)
    assert response.status_code == 403


def test_auditor_can_view_members(client: TestClient, seeded_entities):
    token_auditor = seeded_entities["token_auditor_a"]
    tenant_a_id = str(seeded_entities["tenant_a"].id)

    headers = {"Authorization": f"Bearer {token_auditor}"}
    response = client.get(f"/api/v1/tenants/{tenant_a_id}/members", headers=headers)
    assert response.status_code == 200
    members = response.json()
    assert len(members) >= 3


def test_admin_can_update_settings_and_add_members(client: TestClient, seeded_entities):
    token_admin = seeded_entities["token_admin_a"]
    tenant_a_id = str(seeded_entities["tenant_a"].id)
    headers = {"Authorization": f"Bearer {token_admin}"}

    payload_update = {"settlement_cutoff_time": "18:30"}
    res_update = client.patch(f"/api/v1/tenants/{tenant_a_id}", json=payload_update, headers=headers)
    assert res_update.status_code == 200
    assert res_update.json()["settlement_cutoff_time"] == "18:30"

    reg_payload = {
        "email": "analyst@alpha.com",
        "password": "Password123!",
        "full_name": "New Analyst",
        "tenant_name": "Temporary Tenant",
        "tenant_slug": "temp-slug"
    }
    client.post("/api/v1/auth/register", json=reg_payload)

    add_payload = {"email": "analyst@alpha.com", "role": "AUDITOR"}
    res_add = client.post(f"/api/v1/tenants/{tenant_a_id}/members", json=add_payload, headers=headers)
    assert res_add.status_code == 201
    assert res_add.json()["role"] == "AUDITOR"
