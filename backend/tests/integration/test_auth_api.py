"""
Integration tests for Authentication API endpoints (/api/v1/auth/*).

Verifies:
- POST /api/v1/auth/register: 201 on success, 409 on duplicate email, 422 on invalid input
- POST /api/v1/auth/login: 200 + JWT on valid credentials, 401 on wrong password or unknown user
- GET /api/v1/auth/me: 200 with user profile on valid Bearer token, 401 on missing or tampered token
"""


def test_register_success(client):
    response = client.post(
        "/api/v1/auth/register",
        json={"email": "new.user@example.com", "full_name": "New User", "password": "SecurePassword123!"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "new.user@example.com"
    assert data["full_name"] == "New User"
    assert "password" not in data
    assert "password_hash" not in data


def test_register_duplicate_email_returns_409(client):
    payload = {"email": "duplicate@example.com", "full_name": "Original", "password": "Password123!"}
    res1 = client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == 201

    res2 = client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == 409
    assert "already registered" in res2.json()["detail"].lower()


def test_register_validation_errors(client):
    # Invalid email
    r1 = client.post("/api/v1/auth/register", json={"email": "bad-email", "full_name": "A", "password": "Password123!"})
    assert r1.status_code == 422

    # Blank full_name
    r2 = client.post("/api/v1/auth/register", json={"email": "valid@example.com", "full_name": "   ", "password": "Password123!"})
    assert r2.status_code == 422

    # Short password
    r3 = client.post("/api/v1/auth/register", json={"email": "valid@example.com", "full_name": "A", "password": "short"})
    assert r3.status_code == 422


def test_login_success_and_failures(client):
    # Register user
    client.post(
        "/api/v1/auth/register",
        json={"email": "login.test@example.com", "full_name": "User", "password": "CorrectPassword1!"},
    )

    # Correct credentials -> 200 + token
    success = client.post(
        "/api/v1/auth/login",
        json={"email": "login.test@example.com", "password": "CorrectPassword1!"},
    )
    assert success.status_code == 200
    token_data = success.json()
    assert "access_token" in token_data
    assert token_data["token_type"].lower() == "bearer"

    # Wrong password -> 401
    wrong_pw = client.post(
        "/api/v1/auth/login",
        json={"email": "login.test@example.com", "password": "WrongPassword!"},
    )
    assert wrong_pw.status_code == 401

    # Unknown email -> 401
    unknown = client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@example.com", "password": "CorrectPassword1!"},
    )
    assert unknown.status_code == 401


def test_auth_me_endpoint_security(client):
    # Create user and login
    reg = client.post(
        "/api/v1/auth/register",
        json={"email": "me.user@example.com", "full_name": "Me User", "password": "Password123!"},
    )
    token = client.post(
        "/api/v1/auth/login",
        json={"email": "me.user@example.com", "password": "Password123!"},
    ).json()["access_token"]

    # Valid token -> 200
    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "me.user@example.com"

    # Missing token -> 401
    no_token = client.get("/api/v1/auth/me")
    assert no_token.status_code == 401

    # Tampered token -> 401
    bad_token = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token[:-5]}zzzzz"})
    assert bad_token.status_code == 401
