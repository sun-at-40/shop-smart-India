"""
Price Monitor — Background service that automatically updates prices for tracked products.

Runs in a daemon thread, periodically re-scrapes products with URLs, records
price history, and creates notifications when prices drop or reach target prices.
"""
import json
import threading
import time
import traceback

import config
from database.models import Product, Notification, User
from agent.tools.price_scraper import scrape_price
from agent.tools.currency import format_inr
from agent import notify_channels


_monitor_thread = None
_stop_event = threading.Event()


def _format_inr(value) -> str:
    return format_inr(value)


def check_product(product: dict) -> dict | None:
    """
    Re-scrape a product's price and update it if the price has changed.

    Returns:
        A dict describing the change if updated, otherwise None.
    """
    url = product.get("url")
    if not url:
        return None

    raw = scrape_price(url)
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None

    if not data.get("success") or data.get("price") is None:
        return None

    new_price = float(data["price"])
    old_price = product.get("current_price")

    # No change: skip the update but still treat the scrape as successful.
    if old_price is not None and float(old_price) == new_price:
        return {"product_id": product["id"], "changed": False, "price": new_price}

    Product.update_price(product["id"], new_price, source=product.get("source"))

    change = {
        "product_id": product["id"],
        "name": product["name"],
        "changed": True,
        "old_price": old_price,
        "new_price": new_price,
    }

    # Create an appropriate notification (store it and send it through real channels).
    user_id = product.get("user_id")
    target = product.get("target_price")
    notif_title = notif_message = notif_type = None

    if target is not None and new_price <= float(target):
        notif_title = "🎯 Target price reached!"
        notif_message = (f"'{product['name']}' is now {_format_inr(new_price)} "
                         f"(target: {_format_inr(target)}). This may be a good time to buy!")
        notif_type = "deal"
    elif old_price is not None and new_price < float(old_price):
        notif_title = "📉 Price drop"
        notif_message = (f"'{product['name']}' dropped from {_format_inr(old_price)} "
                         f"to {_format_inr(new_price)}.")
        notif_type = "alert"

    if notif_title:
        Notification.create(
            title=notif_title,
            message=notif_message,
            product_id=product["id"],
            ntype=notif_type,
            user_id=user_id,
        )
        # Send the notification through Telegram/email if the user has configured a channel.
        try:
            user = User.get_by_id(user_id) if user_id else None
            if user:
                full_msg = notif_message
                if product.get("url"):
                    full_msg = f"{notif_message}\n{product['url']}"
                notify_channels.deliver_to_user(user, notif_title, full_msg)
        except Exception:
            traceback.print_exc()

    return change


def run_once(user_id=None) -> int:
    """Check tracked products once and return the number of products updated.

    If ``user_id`` is provided, check only that user's products (for the
    "Refresh prices" button). If None, check all products (for the background job).
    """
    updated = 0
    try:
        products = Product.get_all(user_id=user_id)
    except Exception:
        traceback.print_exc()
        return 0

    for product in products:
        if _stop_event.is_set():
            break
        if not product.get("url"):
            continue
        try:
            result = check_product(product)
            if result and result.get("changed"):
                updated += 1
                print(f"  [PRICE] Updated '{product['name']}': "
                      f"{result.get('old_price')} -> {result.get('new_price')}")
        except Exception:
            traceback.print_exc()
        # Pause between products to avoid rate limiting.
        _stop_event.wait(config.PRICE_MONITOR_PER_ITEM_DELAY)

    return updated


def _monitor_loop():
    print(f"[OK] Price monitor started (interval={config.PRICE_MONITOR_INTERVAL}s).")
    # Wait briefly after startup.
    if _stop_event.wait(config.PRICE_MONITOR_INITIAL_DELAY):
        return
    while not _stop_event.is_set():
        try:
            count = run_once()
            if count:
                print(f"[PRICE] Monitor cycle complete: {count} product(s) updated.")
        except Exception:
            traceback.print_exc()
        # Wait until the next cycle (can be interrupted by stop()).
        if _stop_event.wait(config.PRICE_MONITOR_INTERVAL):
            break


def start_monitor():
    """Start the background monitor (idempotently)."""
    global _monitor_thread
    if not config.PRICE_MONITOR_ENABLED:
        print("[INFO] Price monitor disabled (PRICE_MONITOR_ENABLED=false).")
        return
    if _monitor_thread and _monitor_thread.is_alive():
        return
    _stop_event.clear()
    _monitor_thread = threading.Thread(
        target=_monitor_loop, name="price-monitor", daemon=True
    )
    _monitor_thread.start()


def stop_monitor():
    """Stop the background monitor."""
    _stop_event.set()
