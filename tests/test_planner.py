"""Tests for the Wishlist & Budget Planner (validation, summary, API)."""
from datetime import datetime

import pytest

import planner


def test_clean_item_validates():
    ok = planner.clean_item({"name": " Laptop ", "category": "Laptops", "target_price": "55000"})
    assert ok["name"] == "Laptop" and ok["target_price"] == 55000.0 and ok["priority"] == "medium"
    for bad in ({"name": ""}, {"name": "x", "category": "Nope"}, {"name": "x", "est_price": "-5"},
                {"name": "x", "url": "javascript:alert(1)"}, {"name": "x", "priority": "urgent"}):
        with pytest.raises(ValueError):
            planner.clean_item(bad)


def test_build_summary_budget_spend_and_savings():
    now = datetime(2026, 10, 15)
    items = [
        {"category": "Mobiles", "status": "purchased", "purchased_price": 60000,
         "purchased_at": "2026-10-03 10:00:00", "est_price": 75000},
        {"category": "Mobiles", "status": "purchased", "purchased_price": 9000,
         "purchased_at": "2026-09-20 10:00:00", "est_price": 9000},  # last month: not spent
        {"category": "Mobiles", "status": "wanted", "target_price": 30000, "est_price": 35000},
        {"category": "Books", "status": "wanted", "target_price": None, "est_price": 500},
    ]
    s = planner.build_summary(items, [{"category": "Mobiles", "monthly_limit": 70000}], now=now)
    mob = next(c for c in s["categories"] if c["category"] == "Mobiles")
    assert mob["spent"] == 60000 and mob["remaining"] == 10000
    assert mob["planned"] == 30000 and mob["planned_over"] == 20000
    assert mob["status"] == "warning"
    books = next(c for c in s["categories"] if c["category"] == "Books")
    assert books["status"] == "no_budget" and books["planned"] == 500
    assert s["totals"]["saved"] == 15000 and s["totals"]["spent_this_month"] == 60000


@pytest.fixture
def client(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "DATABASE_PATH", str(tmp_path / "t.db"))
    import app as app_module
    from database.db import init_db
    init_db()
    app_module.app.config["TESTING"] = True
    c = app_module.app.test_client()
    def auth(email):
        r = c.post("/api/auth/register", json={
            "email": email, "password": "secret123", "display_name": "T"}).get_json()
        return {"Authorization": "Bearer " + r["token"]}
    c.auth = auth
    return c


def test_planner_api_flow_and_isolation(client):
    a, b = client.auth("a@x.in"), client.auth("b@x.in")
    r = client.post("/api/planner/items", headers=a, json={
        "name": "Phone", "category": "Mobiles", "est_price": 30000, "target_price": 25000})
    assert r.status_code == 201
    item_id = r.get_json()["item"]["id"]

    assert client.put("/api/planner/budgets", headers=a,
                      json={"category": "Mobiles", "monthly_limit": 40000}).status_code == 200
    assert client.put("/api/planner/budgets", headers=a,
                      json={"category": "Nope", "monthly_limit": 1}).status_code == 400

    # another user cannot touch the item
    assert client.delete(f"/api/planner/items/{item_id}", headers=b).status_code == 404
    assert client.get("/api/planner", headers=b).get_json()["items"] == []

    assert client.post(f"/api/planner/items/{item_id}/track", headers=a).status_code == 200
    assert client.post(f"/api/planner/items/{item_id}/track", headers=a).status_code == 409
    assert client.post(f"/api/planner/items/{item_id}/purchase", headers=a,
                       json={"price": 24000}).status_code == 200

    data = client.get("/api/planner", headers=a).get_json()
    mob = next(c for c in data["summary"]["categories"] if c["category"] == "Mobiles")
    assert mob["spent"] == 24000 and data["summary"]["totals"]["saved"] == 6000

    assert client.post("/api/planner/items", headers=a, json={"name": ""}).status_code == 400
