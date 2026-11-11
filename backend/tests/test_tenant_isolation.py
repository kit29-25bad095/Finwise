from fastapi.testclient import TestClient


def test_tenant_isolation_cannot_access_foreign_tenant(client: TestClient, seeded_entities):
    token_a = seeded_entities["token_admin_a"]
    tenant_b_id = str(seeded_entities["tenant_b"].id)

    headers = {"Authorization": f"Bearer {token_a}"}
    response = client.get(f"/api/v1/tenants/{tenant_b_id}", headers=headers)
    assert response.status_code == 403
    assert "access denied" in response.json()["detail"].lower()


def test_tenant_isolation_cannot_update_foreign_tenant_settings(client: TestClient, seeded_entities):
    token_a = seeded_entities["token_admin_a"]
    tenant_b_id = str(seeded_entities["tenant_b"].id)

    headers = {"Authorization": f"Bearer {token_a}"}
    payload = {"settlement_cutoff_time": "18:00"}
    response = client.patch(f"/api/v1/tenants/{tenant_b_id}", json=payload, headers=headers)
    assert response.status_code == 403


def test_tenant_isolation_cannot_add_members_to_foreign_tenant(client: TestClient, seeded_entities):
    token_a = seeded_entities["token_admin_a"]
    tenant_b_id = str(seeded_entities["tenant_b"].id)

    headers = {"Authorization": f"Bearer {token_a}"}
    payload = {"email": "manager@alpha.com", "role": "FINANCE_MANAGER"}
    response = client.post(f"/api/v1/tenants/{tenant_b_id}/members", json=payload, headers=headers)
    assert response.status_code == 403


def test_tenant_isolation_cannot_list_foreign_tenant_members(client: TestClient, seeded_entities):
    token_a = seeded_entities["token_admin_a"]
    tenant_b_id = str(seeded_entities["tenant_b"].id)

    headers = {"Authorization": f"Bearer {token_a}"}
    response = client.get(f"/api/v1/tenants/{tenant_b_id}/members", headers=headers)
    assert response.status_code == 403


def test_legitimate_tenant_access_succeeds(client: TestClient, seeded_entities):
    token_a = seeded_entities["token_admin_a"]
    tenant_a_id = str(seeded_entities["tenant_a"].id)

    headers = {"Authorization": f"Bearer {token_a}"}
    response = client.get(f"/api/v1/tenants/{tenant_a_id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Alpha D2C Brands"
    assert data["slug"] == "alpha-d2c"
