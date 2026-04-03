

class TestRegister:
    async def test_register_success(self, client):
        response = await client.post("/api/v1/auth/register", json={
            "email": "new@example.com",
            "username": "newuser",
            "password": "securepass123",
        })
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "new@example.com"
        assert data["username"] == "newuser"
        assert data["role"] == "free"

    async def test_register_duplicate_email(self, client):
        payload = {
            "email": "dup@example.com",
            "username": "user1",
            "password": "securepass123",
        }
        await client.post("/api/v1/auth/register", json=payload)
        payload["username"] = "user2"
        response = await client.post("/api/v1/auth/register", json=payload)
        assert response.status_code == 400
        assert "Email already registered" in response.json()["detail"]

    async def test_register_short_password(self, client):
        response = await client.post("/api/v1/auth/register", json={
            "email": "short@example.com",
            "username": "shortpw",
            "password": "123",
        })
        assert response.status_code == 422


class TestLogin:
    async def test_login_success(self, client):
        # Register first
        await client.post("/api/v1/auth/register", json={
            "email": "login@example.com",
            "username": "loginuser",
            "password": "securepass123",
        })
        # Login
        response = await client.post("/api/v1/auth/login", json={
            "email": "login@example.com",
            "password": "securepass123",
        })
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert "refresh_token" in data
        assert data["token_type"] == "bearer"

    async def test_login_wrong_password(self, client):
        await client.post("/api/v1/auth/register", json={
            "email": "wrong@example.com",
            "username": "wrongpw",
            "password": "securepass123",
        })
        response = await client.post("/api/v1/auth/login", json={
            "email": "wrong@example.com",
            "password": "wrongpassword",
        })
        assert response.status_code == 401

    async def test_login_nonexistent(self, client):
        response = await client.post("/api/v1/auth/login", json={
            "email": "noone@example.com",
            "password": "whatever123",
        })
        assert response.status_code == 401


class TestRefresh:
    async def test_refresh_token(self, client):
        await client.post("/api/v1/auth/register", json={
            "email": "refresh@example.com",
            "username": "refreshuser",
            "password": "securepass123",
        })
        login = await client.post("/api/v1/auth/login", json={
            "email": "refresh@example.com",
            "password": "securepass123",
        })
        refresh_token = login.json()["refresh_token"]

        response = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": refresh_token,
        })
        assert response.status_code == 200
        assert "access_token" in response.json()

    async def test_refresh_invalid_token(self, client):
        response = await client.post("/api/v1/auth/refresh", json={
            "refresh_token": "invalid-token",
        })
        assert response.status_code == 401


class TestMe:
    async def test_me_authenticated(self, client, auth_headers):
        response = await client.get("/api/v1/auth/me", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email"] == "test@example.com"
        assert data["username"] == "testuser"

    async def test_me_unauthenticated(self, client):
        response = await client.get("/api/v1/auth/me")
        assert response.status_code == 401
