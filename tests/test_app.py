import os
import uuid
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("MONGO_URI", "mongodb://127.0.0.1:27017")
os.environ["MONGO_DATABASE"] = "payments_lab_test_" + uuid.uuid4().hex

import pytest
from fastapi.testclient import TestClient
from app import app, database


@pytest.fixture(scope="module", autouse=True)
def clean_test_database():
    yield
    db = database()
    assert db.name.startswith("payments_lab_test_")
    db.client.drop_database(db.name)
    db.client.close()
    database.cache_clear()


def test_paid_declined_and_session_isolation():
    with TestClient(app) as client:
        paid = client.post("/api/orders", json={"amount": 4200, "currency": "INR"})
        assert paid.status_code == 201
        order = paid.json()
        assert order["status"] == "paid"
        assert client.get("/api/orders/" + order["id"]).json() == order
        assert (
            client.post(
                "/api/orders",
                json={"amount": 1500, "currency": "INR", "outcome": "failure"},
            ).json()["status"]
            == "failed"
        )
        assert len(client.get("/api/orders").json()["orders"]) == 2
        with TestClient(app) as other:
            assert other.get("/api/orders/" + order["id"]).status_code == 404
            assert other.get("/api/orders").json()["orders"] == []


def test_real_mongo_atomic_concurrency_and_conflict():
    with TestClient(app) as client:
        client.get("/api/orders")
        payload = {"order_id": "test-order", "amount": 4200, "currency": "INR"}
        headers = {"Idempotency-Key": "concurrent-key"}
        cookies = dict(client.cookies)

        def send(_):
            with TestClient(app, cookies=cookies) as concurrent:
                return concurrent.post("/api/payments", json=payload, headers=headers)

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(send, range(8)))
        assert all(r.status_code == 200 for r in results)
        assert len({r.json()["transaction_id"] for r in results}) == 1
        assert (
            database().transactions.count_documents(
                {"session": cookies["payments_session"], "key": "concurrent-key"}
            )
            == 1
        )
        assert (
            client.post(
                "/api/payments", json={**payload, "amount": 4300}, headers=headers
            ).status_code
            == 409
        )


def test_pending_order_recovers_committed_payment():
    with TestClient(app) as client:
        created = client.post(
            "/api/orders", json={"amount": 4200, "currency": "INR"}
        ).json()
        database().orders.update_one(
            {"_id": created["id"]},
            {"$set": {"status": "pending", "transaction_id": None}},
        )
        recovered = client.get("/api/orders/" + created["id"]).json()
        assert recovered["status"] == "paid"
        assert recovered["transaction_id"] == created["transaction_id"]


def test_validation_origin_rate_limit_and_health():
    with TestClient(app) as client:
        client.get("/api/orders")
        payload = {"amount": 4200, "currency": "INR"}
        assert (
            client.post("/api/orders", json={**payload, "amount": 42.5}).status_code
            == 422
        )
        assert (
            client.post(
                "/api/orders", json=payload, headers={"Origin": "https://evil.example"}
            ).status_code
            == 403
        )
        assert client.get("/api/health").json()["status"] == "ready"
        sid = client.cookies["payments_session"]
        import time

        database().limits.update_one(
            {"_id": f"{sid}:{int(time.time() // 60)}"},
            {"$set": {"count": 30}},
            upsert=True,
        )
        assert client.post("/api/orders", json=payload).status_code == 429
