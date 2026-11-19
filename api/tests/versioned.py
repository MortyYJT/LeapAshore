"""Writes the way a client sends them since records carry versions: read the version, then state it.

An update names the version it was based on (`app/services/versions.py`), so a test that is about
something else still has to send one. These helpers read the stored version through the same routes a
client uses and restate it, which keeps the version out of tests that do not assert on it. A row the
caller cannot read (another subject's, or none) is sent with a version no row holds, so the route's
own 404 is what answers.
"""

from fastapi.testclient import TestClient

NO_SUCH_VERSION = 0


def portfolio_base(client: TestClient) -> list[dict]:
    return [
        {"id": row["id"], "version": row["version"]}
        for row in client.get("/api/applications").json()
    ]


def put_portfolio(client: TestClient, rows: list[dict]):
    return client.put("/api/applications", json={"rows": rows, "base": portfolio_base(client)})


def patch_profile(client: TestClient, body: dict):
    """A profile edit based on the stored version. The read creates the subject, as a browser's does."""
    version = client.get("/api/profile").json()["version"]
    return client.patch("/api/profile", json={**body, "baseVersion": version})


def task_version(client: TestClient, task_id: str) -> int:
    tasks = client.get("/api/roadmap").json()["tasks"]
    return next((task["version"] for task in tasks if task["id"] == task_id), NO_SUCH_VERSION)


def patch_task(client: TestClient, task_id: str, body: dict):
    return client.patch(
        f"/api/roadmap/tasks/{task_id}",
        json={**body, "baseVersion": task_version(client, task_id)},
    )


def record_version(client: TestClient, key: str) -> str:
    records = client.get("/api/application-records").json()
    return next((r["version"] for r in records if r["id"] == key), str(NO_SUCH_VERSION))


def patch_record(client: TestClient, key: str, body: dict):
    return client.patch(
        f"/api/application-records/{key}",
        json={**body, "baseVersion": record_version(client, key)},
    )


def delete_record(client: TestClient, key: str):
    return client.delete(
        f"/api/application-records/{key}", params={"baseVersion": record_version(client, key)}
    )


def create_record(client: TestClient, body: dict, key: str | None = None):
    import uuid

    return client.post(
        "/api/application-records",
        json=body,
        headers={"Idempotency-Key": key or str(uuid.uuid4())},
    )
