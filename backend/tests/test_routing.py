from app.main import app


def test_every_api_route_is_versioned():
    unversioned = [path for path in app.openapi()["paths"] if not path.startswith("/api/v1/") and path != "/health"]
    assert unversioned == []


async def test_old_unversioned_routes_are_gone(client):
    response = await client.post("/auth/login", json={"email": "a@example.com", "password": "x"})
    assert response.status_code == 404


async def test_health(client):
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
