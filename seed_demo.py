"""
Load demo data for ShopSmart (Indian market) so the Dashboard, price charts and
notifications have something meaningful to show.

Usage:
    python seed_demo.py            # create/refresh the demo account's data
    python seed_demo.py --reset    # same, but wipes existing demo data first

Demo login:  demo@shopsmart.in  /  Demo@1234
The script only touches the demo account; other users' data is never modified.
"""
import argparse
import random
import sqlite3
from datetime import datetime, timedelta

import auth
from database.db import get_db, init_db

# Store datetimes in SQLite's native text format (the default adapter is deprecated).
sqlite3.register_adapter(datetime, lambda d: d.strftime("%Y-%m-%d %H:%M:%S"))

DEMO_EMAIL = "demo@shopsmart.in"
DEMO_NAME = "Demo User"
DEMO_PASSWORD = "Demo@1234"
DAYS = 60

# name, source, url, start_price, end_price, target, volatility, shape
# shape: "drop" = gradual fall, "rise" = gradual climb, "flat" = stable,
#        "sale" = dips sharply near the end, "spike" = brief jump mid-way.
PRODUCTS = [
    ("Apple iPhone 16 128GB (Black)", "Amazon India",
     "https://www.amazon.in/dp/B0DGHYPS2H", 79900, 72490, 70000, 0.006, "drop"),
    ("Samsung Galaxy S24 5G 256GB", "Flipkart",
     "https://www.flipkart.com/samsung-galaxy-s24-5g/p/itm0001", 79999, 61999, 60000, 0.008, "drop"),
    ("OnePlus 12 5G (16GB/512GB)", "Croma",
     "https://www.croma.com/oneplus-12-5g/p/300001", 69999, 64999, 62000, 0.005, "sale"),
    ("Sony WH-1000XM5 Wireless Headphones", "Amazon India",
     "https://www.amazon.in/dp/B09XS7JWHH", 34990, 24990, 22000, 0.012, "drop"),
    ("boAt Rockerz 450 Bluetooth Headphones", "Flipkart",
     "https://www.flipkart.com/boat-rockerz-450/p/itm0002", 1499, 1299, 1199, 0.015, "flat"),
    ("Samsung 55\" Crystal 4K Smart TV", "Reliance Digital",
     "https://www.reliancedigital.in/samsung-55-crystal-4k/p/493000", 52990, 42990, 40000, 0.007, "sale"),
    ("LG 8 kg 5 Star Front Load Washing Machine", "Vijay Sales",
     "https://www.vijaysales.com/p/lg-8kg-front-load", 38990, 40990, 36000, 0.006, "rise"),
    ("Apple MacBook Air M2 13\" 256GB", "Tata CLiQ",
     "https://www.tatacliq.com/apple-macbook-air-m2/p-mp000000", 99900, 89990, 85000, 0.005, "drop"),
    ("Nike Revolution 7 Running Shoes", "Myntra",
     "https://www.myntra.com/nike-revolution-7/buy", 3995, 2799, 2500, 0.02, "spike"),
    ("Prestige Induction Cooktop PIC 20", "Snapdeal",
     "https://www.snapdeal.com/product/prestige-pic-20/6000001", 2495, 2495, 2000, 0.004, "flat"),
]


def _price_path(start, end, vol, shape, rng):
    """Daily price series of length DAYS+1 ending exactly at `end`."""
    prices = []
    for i in range(DAYS + 1):
        t = i / DAYS
        if shape == "drop":
            base = start + (end - start) * (t ** 0.8)
        elif shape == "rise":
            base = start + (end - start) * (t ** 1.2)
        elif shape == "sale":
            base = start - (start - end * 1.08) * t if t < 0.85 else end * 1.08 - (end * 1.08 - end) * ((t - 0.85) / 0.15)
        elif shape == "spike":
            base = start + (end - start) * t
            if 0.4 < t < 0.55:
                base *= 1.12
        else:
            base = start + (end - start) * t
        noise = rng.uniform(-vol, vol)
        prices.append(round(base * (1 + noise)))
    prices[-1] = round(end)
    return prices


def _get_or_create_demo_user(conn):
    row = conn.execute("SELECT id FROM users WHERE email = ?", (DEMO_EMAIL,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO users (email, display_name, password_hash) VALUES (?, ?, ?)",
        (DEMO_EMAIL, DEMO_NAME, auth.hash_password(DEMO_PASSWORD)),
    )
    return cur.lastrowid


def _seed_planner(conn, user_id, now):
    """Budgets plus wishlist items (some purchased this month) for the planner demo."""
    conn.execute("DELETE FROM wishlist_items WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM budgets WHERE user_id = ?", (user_id,))
    for category, limit in [("Mobiles", 70000), ("Laptops", 100000),
                            ("Electronics", 40000), ("Home & Kitchen", 25000)]:
        conn.execute("INSERT INTO budgets (user_id, category, monthly_limit) VALUES (?, ?, ?)",
                     (user_id, category, limit))

    # (name, category, est, target, priority, paid, days_ago_bought)
    items = [
        ("Samsung Galaxy S24 5G 256GB", "Mobiles", 74999, 60000, "high", 59999, 4),
        ("boAt Airdopes 141 Earbuds", "Electronics", 1999, 1299, "low", 1299, 6),
        ("Prestige Induction Cooktop", "Home & Kitchen", 3499, 2500, "low", 2699, 1),
        ("Apple MacBook Air M2 13\"", "Laptops", 99900, 85000, "high", None, None),
        ("Sony WH-1000XM5 Headphones", "Electronics", 29990, 24000, "medium", None, None),
        ("Dyson V8 Cordless Vacuum", "Home & Kitchen", 36900, 28000, "medium", None, None),
        ("Atomic Habits (Paperback)", "Books", 650, 399, "low", None, None),
    ]
    for name, cat, est, target, pri, paid, ago in items:
        bought = (now - timedelta(days=ago)) if paid else None
        conn.execute(
            """INSERT INTO wishlist_items
               (user_id, name, category, est_price, target_price, priority, status,
                purchased_price, purchased_at, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, name, cat, est, target, pri, "purchased" if paid else "wanted",
             paid, bought.strftime("%Y-%m-%d %H:%M:%S") if bought else None,
             now - timedelta(days=20)),
        )


def seed(reset=False):
    init_db()
    rng = random.Random(42)  # deterministic so every demo looks the same
    now = datetime.now().replace(microsecond=0)

    with get_db() as conn:
        user_id = _get_or_create_demo_user(conn)

        existing = conn.execute(
            "SELECT COUNT(*) AS n FROM products WHERE user_id = ?", (user_id,)
        ).fetchone()["n"]
        if existing and not reset:
            print(f"Demo data already present ({existing} products). Use --reset to reload.")
            return
        if reset:
            conn.execute("DELETE FROM notifications WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM chat_history WHERE user_id = ?", (user_id,))
            conn.execute("DELETE FROM products WHERE user_id = ?", (user_id,))  # cascades history

        ids = {}
        for name, source, url, start, end, target, vol, shape in PRODUCTS:
            series = _price_path(start, end, vol, shape, rng)
            added = now - timedelta(days=DAYS)
            cur = conn.execute(
                """INSERT INTO products
                   (user_id, name, url, source, current_price, target_price, currency,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'INR', ?, ?)""",
                (user_id, name, url, source, series[-1], target, added, now),
            )
            pid = cur.lastrowid
            ids[name] = (pid, series[-1], target)
            # One price point every 2 days plus the latest one.
            for day in list(range(0, DAYS, 2)) + [DAYS]:
                ts = added + timedelta(days=day, hours=rng.randint(0, 5))
                if day == DAYS:
                    ts = now
                conn.execute(
                    "INSERT INTO price_history (product_id, price, source, recorded_at) "
                    "VALUES (?, ?, ?, ?)",
                    (pid, series[day], source, ts),
                )

        def notify(name, title, message, ntype, hours_ago, read=False):
            pid = ids[name][0]
            conn.execute(
                """INSERT INTO notifications
                   (user_id, product_id, title, message, type, is_read, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, pid, title, message, ntype, 1 if read else 0,
                 now - timedelta(hours=hours_ago)),
            )

        notify("Samsung Galaxy S24 5G 256GB", "🎯 Target price reached!",
               "'Samsung Galaxy S24 5G 256GB' is now ₹61,999 (target ₹60,000). Great time to buy!",
               "alert", 3)
        notify("Sony WH-1000XM5 Wireless Headphones", "📉 Price drop",
               "'Sony WH-1000XM5 Wireless Headphones' dropped from ₹27,490 to ₹24,990.",
               "deal", 9)
        notify("Samsung 55\" Crystal 4K Smart TV", "📉 Price drop",
               "'Samsung 55\" Crystal 4K Smart TV' dropped from ₹46,490 to ₹42,990.",
               "deal", 26)
        notify("Apple MacBook Air M2 13\" 256GB", "📉 Price drop",
               "'Apple MacBook Air M2 13\" 256GB' dropped from ₹94,990 to ₹89,990.",
               "deal", 50, read=True)
        notify("LG 8 kg 5 Star Front Load Washing Machine", "📈 Price increase",
               "'LG 8 kg 5 Star Front Load Washing Machine' rose to ₹40,990. Consider buying soon.",
               "info", 72, read=True)
        notify("Apple iPhone 16 128GB (Black)", "📌 Added to tracking",
               "'Apple iPhone 16 128GB (Black)' was added to your price-tracking list.",
               "tracking", DAYS * 24, read=True)

        _seed_planner(conn, user_id, now)

    print(f"Loaded {len(PRODUCTS)} demo products with {DAYS} days of price history.")
    print(f"Login: {DEMO_EMAIL} / {DEMO_PASSWORD}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Load ShopSmart demo data.")
    parser.add_argument("--reset", action="store_true", help="wipe existing demo data first")
    seed(parser.parse_args().reset)
