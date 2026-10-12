"""
Wishlist & Budget Planner models (all queries are scoped to a user).
"""
from datetime import datetime

from database.db import get_db

_ITEM_FIELDS = ("name", "category", "url", "est_price", "target_price",
                "priority", "notes")


def _rows(cursor):
    return [dict(r) for r in cursor.fetchall()]


class Wishlist:
    @staticmethod
    def create(user_id, name, category="Other", url=None, est_price=None,
               target_price=None, priority="medium", notes=None):
        with get_db() as conn:
            cur = conn.execute(
                """INSERT INTO wishlist_items
                   (user_id, name, category, url, est_price, target_price, priority, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, name, category, url, est_price, target_price, priority, notes),
            )
            return cur.lastrowid

    @staticmethod
    def get_all(user_id):
        with get_db() as conn:
            return _rows(conn.execute(
                "SELECT * FROM wishlist_items WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                (user_id,),
            ))

    @staticmethod
    def get(item_id, user_id):
        with get_db() as conn:
            row = conn.execute(
                "SELECT * FROM wishlist_items WHERE id = ? AND user_id = ?",
                (item_id, user_id),
            ).fetchone()
            return dict(row) if row else None

    @staticmethod
    def update(item_id, user_id, **fields):
        fields = {k: v for k, v in fields.items() if k in _ITEM_FIELDS}
        if not fields:
            return
        cols = ", ".join(f"{k} = ?" for k in fields)
        with get_db() as conn:
            conn.execute(
                f"UPDATE wishlist_items SET {cols} WHERE id = ? AND user_id = ?",
                (*fields.values(), item_id, user_id),
            )

    @staticmethod
    def mark_purchased(item_id, user_id, price, when=None):
        with get_db() as conn:
            conn.execute(
                """UPDATE wishlist_items
                   SET status = 'purchased', purchased_price = ?, purchased_at = ?
                   WHERE id = ? AND user_id = ?""",
                (price, (when or datetime.now()).strftime("%Y-%m-%d %H:%M:%S"),
                 item_id, user_id),
            )

    @staticmethod
    def mark_wanted(item_id, user_id):
        with get_db() as conn:
            conn.execute(
                """UPDATE wishlist_items
                   SET status = 'wanted', purchased_price = NULL, purchased_at = NULL
                   WHERE id = ? AND user_id = ?""",
                (item_id, user_id),
            )

    @staticmethod
    def set_tracked(item_id, user_id, product_id):
        with get_db() as conn:
            conn.execute(
                "UPDATE wishlist_items SET tracked_product_id = ? WHERE id = ? AND user_id = ?",
                (product_id, item_id, user_id),
            )

    @staticmethod
    def delete(item_id, user_id):
        with get_db() as conn:
            conn.execute(
                "DELETE FROM wishlist_items WHERE id = ? AND user_id = ?",
                (item_id, user_id),
            )


class Budget:
    @staticmethod
    def get_all(user_id):
        with get_db() as conn:
            return _rows(conn.execute(
                "SELECT category, monthly_limit FROM budgets WHERE user_id = ? ORDER BY category",
                (user_id,),
            ))

    @staticmethod
    def upsert(user_id, category, monthly_limit):
        with get_db() as conn:
            conn.execute(
                """INSERT INTO budgets (user_id, category, monthly_limit) VALUES (?, ?, ?)
                   ON CONFLICT(user_id, category) DO UPDATE SET monthly_limit = excluded.monthly_limit""",
                (user_id, category, monthly_limit),
            )

    @staticmethod
    def delete(user_id, category):
        with get_db() as conn:
            conn.execute(
                "DELETE FROM budgets WHERE user_id = ? AND category = ?",
                (user_id, category),
            )
