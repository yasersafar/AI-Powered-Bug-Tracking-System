def auth_headers(client, email, role):
    client.post(
        "/auth/register",
        json={
            "email": email,
            "full_name": "Test User",
            "password": "secret123",
            "role": role,
        },
    )
    r = client.post(
        "/auth/login", data={"username": email, "password": "secret123"}
    )
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_requires_authentication(client):
    resp = client.get("/projects")
    assert resp.status_code == 401


def test_reporter_cannot_create_project(client):
    headers = auth_headers(client, "rep@example.com", "reporter")
    resp = client.post("/projects", json={"name": "P1"}, headers=headers)
    assert resp.status_code == 403


def test_project_manager_can_create_project(client):
    headers = auth_headers(client, "pm@example.com", "project_manager")
    resp = client.post(
        "/projects", json={"name": "P1", "description": "x"}, headers=headers
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "P1"


def test_non_member_cannot_access_project(client):
    pm = auth_headers(client, "pm2@example.com", "project_manager")
    created = client.post("/projects", json={"name": "Secret"}, headers=pm)
    pid = created.json()["id"]

    dev = auth_headers(client, "dev2@example.com", "developer")
    resp = client.get(f"/projects/{pid}", headers=dev)
    assert resp.status_code == 403
