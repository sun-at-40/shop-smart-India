"""
Wishlist & Budget Planner — validation and summary logic (pure, no DB access).
"""
from datetime import datetime

CATEGORIES = ["Mobiles", "Laptops", "Electronics", "Appliances",
              "Fashion", "Home & Kitchen", "Books", "Other"]
PRIORITIES = ["high", "medium", "low"]


def _price(value, field, required=False):
    """Parse an optional positive price; raises ValueError with a user-facing message."""
    if value in (None, ""):
        if required:
            raise ValueError(f"{field} is required")
        return None
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number")
    if not (0 < num <= 100_000_000):
        raise ValueError(f"{field} must be greater than 0")
    return num


def clean_item(data: dict, partial=False) -> dict:
    """Validate wishlist item input. With partial=True only supplied keys are returned."""
    out = {}
    if not partial or "name" in data:
        name = (data.get("name") or "").strip()
        if not name:
            raise ValueError("Item name is required")
        out["name"] = name[:200]
    if not partial or "category" in data:
        cat = data.get("category") or "Other"
        if cat not in CATEGORIES:
            raise ValueError("Unknown category")
        out["category"] = cat
    if not partial or "priority" in data:
        pri = data.get("priority") or "medium"
        if pri not in PRIORITIES:
            raise ValueError("Priority must be high, medium or low")
        out["priority"] = pri
    for key in ("est_price", "target_price"):
        if not partial or key in data:
            out[key] = _price(data.get(key), key)
    if not partial or "url" in data:
        url = (data.get("url") or "").strip()
        if url and not url.lower().startswith(("http://", "https://")):
            raise ValueError("URL must start with http:// or https://")
        out["url"] = url or None
    if not partial or "notes" in data:
        out["notes"] = ((data.get("notes") or "").strip()[:500]) or None
    return out


def clean_budget(data: dict) -> tuple:
    category = data.get("category")
    if category not in CATEGORIES:
        raise ValueError("Unknown category")
    return category, _price(data.get("monthly_limit"), "monthly_limit", required=True)


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.strptime(str(value)[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def build_summary(items, budgets, now=None) -> dict:
    """
    Combine wishlist items and budgets into the planner overview.

    Per category: monthly budget, spent this month (items purchased this calendar
    month), planned (open wishlist items at target price, else estimate) and
    what is left. Savings = estimate - paid, for purchased items paid below estimate.
    """
    now = now or datetime.now()
    limits = {b["category"]: b["monthly_limit"] for b in budgets}
    cats = {}

    def row(cat):
        return cats.setdefault(cat, {
            "category": cat, "budget": limits.get(cat), "spent": 0.0,
            "planned": 0.0, "open_items": 0,
        })

    for cat in limits:
        row(cat)

    total_saved = 0.0
    for it in items:
        r = row(it["category"])
        if it["status"] == "purchased":
            paid = it.get("purchased_price") or 0.0
            when = _parse_dt(it.get("purchased_at"))
            if when and (when.year, when.month) == (now.year, now.month):
                r["spent"] += paid
            est = it.get("est_price")
            if est and paid and paid < est:
                total_saved += est - paid
        else:
            r["open_items"] += 1
            r["planned"] += it.get("target_price") or it.get("est_price") or 0.0

    for r in cats.values():
        if r["budget"]:
            r["remaining"] = r["budget"] - r["spent"]
            r["planned_over"] = max(0.0, r["spent"] + r["planned"] - r["budget"])
            r["used_pct"] = round(r["spent"] / r["budget"] * 100, 1)
            r["status"] = ("over" if r["spent"] > r["budget"]
                           else "warning" if r["used_pct"] >= 80 else "ok")
        else:
            r["remaining"] = r["planned_over"] = r["used_pct"] = None
            r["status"] = "no_budget"

    categories = sorted(cats.values(), key=lambda r: r["category"])
    return {
        "categories": categories,
        "totals": {
            "budget": sum(limits.values()),
            "spent_this_month": sum(r["spent"] for r in categories),
            "planned": sum(r["planned"] for r in categories),
            "saved": total_saved,
            "open_items": sum(r["open_items"] for r in categories),
        },
    }
