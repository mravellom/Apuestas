

class TestUserConfig:
    async def test_get_config(self, client, auth_headers):
        response = await client.get("/api/v1/users/config", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["default_staking"] == "fractional_kelly"
        assert data["risk_tolerance"] == "moderate"

    async def test_update_config(self, client, auth_headers):
        response = await client.put("/api/v1/users/config", headers=auth_headers, json={
            "default_staking": "flat",
            "risk_tolerance": "conservative",
        })
        assert response.status_code == 200
        data = response.json()
        assert data["default_staking"] == "flat"
        assert data["risk_tolerance"] == "conservative"

    async def test_config_unauthenticated(self, client):
        response = await client.get("/api/v1/users/config")
        assert response.status_code == 401


class TestBankroll:
    async def test_create_bankroll(self, client, auth_headers):
        response = await client.post("/api/v1/users/bankroll", headers=auth_headers, json={
            "name": "Test Bankroll",
            "currency": "EUR",
            "initial_amount": 1000.0,
        })
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Bankroll"
        assert data["initial_amount"] == 1000.0
        assert data["current_amount"] == 1000.0

    async def test_list_bankrolls(self, client, auth_headers):
        await client.post("/api/v1/users/bankroll", headers=auth_headers, json={
            "name": "BR1",
            "initial_amount": 500.0,
        })
        response = await client.get("/api/v1/users/bankroll", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    async def test_update_bankroll(self, client, auth_headers):
        create = await client.post("/api/v1/users/bankroll", headers=auth_headers, json={
            "name": "Update Test",
            "initial_amount": 1000.0,
        })
        bankroll_id = create.json()["id"]

        response = await client.put(
            f"/api/v1/users/bankroll/{bankroll_id}",
            headers=auth_headers,
            json={"name": "Updated Name", "current_amount": 1200.0},
        )
        assert response.status_code == 200
        assert response.json()["name"] == "Updated Name"
        assert response.json()["current_amount"] == 1200.0
