from fastapi.testclient import TestClient


def test_register_new_tenant_and_user_success(client: TestClient):
    payload = {
        "email": "cfo@newbrand.com",
        "password": "SecurePassword999!",
        "full_name": "Chief Financial Officer",
        "tenant_name": "New D2C Direct",
        "tenant_slug": "new-d2c"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert "access_token" in data
    assert data["user"]["email"] == "cfo@newbrand.com"
    assert data["active_role"] == "ADMIN"
    assert len(data["memberships"]) == 1


def test_register_duplicate_email_rejected(client: TestClient, seeded_entities):
    payload = {
        "email": "admin@alpha.com",
        "password": "Password123!",
        "full_name": "Another Admin",
        "tenant_name": "Duplicate Co",
        "tenant_slug": "duplicate-co"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"].lower()


def test_register_duplicate_slug_rejected(client: TestClient, seeded_entities):
    payload = {
        "email": "unique_email@brand.com",
        "password": "Password123!",
        "full_name": "Brand Owner",
        "tenant_name": "Alpha Duplicate Slug",
        "tenant_slug": "alpha-d2c"
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 400
    assert "identifier already exists" in response.json()["detail"].lower()


def test_login_success(client: TestClient, seeded_entities):
    payload = {
        "email": "admin@alpha.com",
        "password": "Password123!"
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["active_role"] == "ADMIN"
    assert data["user"]["email"] == "admin@alpha.com"


def test_login_invalid_password(client: TestClient, seeded_entities):
    payload = {
        "email": "admin@alpha.com",
        "password": "WrongPassword!"
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401
    assert "incorrect" in response.json()["detail"].lower()


def test_get_current_user_profile(client: TestClient, seeded_entities):
    token = seeded_entities["token_admin_a"]
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "admin@alpha.com"
    assert data["full_name"] == "Alpha Admin"
