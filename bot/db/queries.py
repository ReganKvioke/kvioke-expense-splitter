"""All database read/write functions. Each function opens+closes its own connection so
they are safe to call from async context via run_in_executor."""
import sqlite3
import logging
from typing import Optional
from bot.db.database import get_connection
from bot.utils.format import now_utc_iso

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def upsert_user(telegram_id: str, display_name: str) -> int:
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT OR IGNORE INTO users (telegram_id, display_name) VALUES (?, ?)",
                (telegram_id, display_name),
            )
            conn.execute(
                "UPDATE users SET display_name = ? WHERE telegram_id = ?",
                (display_name, telegram_id),
            )
        row = conn.execute(
            "SELECT id FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return row["id"]
    finally:
        conn.close()


def get_user_by_telegram_id(telegram_id: str) -> Optional[sqlite3.Row]:
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
    finally:
        conn.close()


def get_user_by_username(username: str) -> Optional[sqlite3.Row]:
    """Match by display_name (username without @)."""
    conn = get_connection()
    try:
        return conn.execute(
            "SELECT * FROM users WHERE display_name = ?", (username.lstrip("@"),)
        ).fetchone()
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, telegram_id, display_name, is_guest FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_guest_users() -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, display_name FROM users WHERE is_guest = 1 ORDER BY display_name"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_guest_linked_count(user_id: int) -> dict:
    """Return counts of records that reference this guest user."""
    conn = get_connection()
    try:
        expenses_paid = conn.execute(
            "SELECT COUNT(*) AS cnt FROM expenses WHERE paid_by_user_id = ?", (user_id,)
        ).fetchone()["cnt"]
        splits = conn.execute(
            "SELECT COUNT(*) AS cnt FROM expense_splits WHERE user_id = ?", (user_id,)
        ).fetchone()["cnt"]
        settlements = conn.execute(
            "SELECT COUNT(*) AS cnt FROM settlements WHERE from_user_id = ? OR to_user_id = ?",
            (user_id, user_id),
        ).fetchone()["cnt"]
        return {"expenses_paid": expenses_paid, "splits": splits, "settlements": settlements}
    finally:
        conn.close()


def delete_guest_user(user_id: int) -> bool:
    """Delete a guest user, their trip participant entries, and any settlements they appear in.
    Raises (via FK constraint) if they still have linked expenses or expense splits."""
    conn = get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM trip_participants WHERE user_id = ?", (user_id,))
            conn.execute(
                "DELETE FROM settlements WHERE from_user_id = ? OR to_user_id = ?",
                (user_id, user_id),
            )
            cur = conn.execute(
                "DELETE FROM users WHERE id = ? AND is_guest = 1", (user_id,)
            )
        return cur.rowcount > 0
    finally:
        conn.close()


def get_all_known_users(exclude_telegram_id: str | None = None) -> list:
    """Return all users (authorized + guests). Optionally exclude one telegram_id (the caller)."""
    conn = get_connection()
    try:
        if exclude_telegram_id:
            rows = conn.execute(
                "SELECT id, telegram_id, display_name, is_guest FROM users "
                "WHERE telegram_id != ? ORDER BY is_guest, display_name",
                (exclude_telegram_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, telegram_id, display_name, is_guest FROM users "
                "ORDER BY is_guest, display_name"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def create_guest_user(display_name: str) -> int:
    """Create a guest user (no Telegram account) and return their db id."""
    import uuid
    synthetic_id = f"guest:{uuid.uuid4().hex}"
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO users (telegram_id, display_name, is_guest) VALUES (?, ?, 1)",
                (synthetic_id, display_name.strip()),
            )
        return cur.lastrowid
    finally:
        conn.close()


def get_all_users_in_group(group_chat_id: str) -> list:
    """Return all users who have ever participated in this group (paid or split)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT DISTINCT u.id, u.telegram_id, u.display_name
            FROM users u
            WHERE u.id IN (
                SELECT paid_by_user_id FROM expenses WHERE group_chat_id = ?
                UNION
                SELECT es.user_id FROM expense_splits es
                JOIN expenses e ON e.id = es.expense_id
                WHERE e.group_chat_id = ?
            )
            ORDER BY u.display_name
            """,
            (group_chat_id, group_chat_id),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Authorized users / auth
# ---------------------------------------------------------------------------

def is_authorized(telegram_id: str, admin_ids: list[str]) -> bool:
    if str(telegram_id) in [str(a) for a in admin_ids]:
        return True
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id FROM authorized_users WHERE telegram_id = ?",
            (str(telegram_id),),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


def authorize_user(telegram_id: str, authorized_by: str) -> None:
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO authorized_users (telegram_id, authorized_at, authorized_by)
                VALUES (?, ?, ?)
                """,
                (str(telegram_id), now_utc_iso(), authorized_by),
            )
    finally:
        conn.close()


def revoke_user(telegram_id: str) -> bool:
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM authorized_users WHERE telegram_id = ?",
                (str(telegram_id),),
            )
        return cur.rowcount > 0
    finally:
        conn.close()


def get_all_authorized_users() -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT telegram_id, authorized_at, authorized_by FROM authorized_users ORDER BY authorized_at"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def count_recent_auth_attempts(telegram_id: str, window_seconds: int) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*) AS cnt FROM auth_attempts
            WHERE telegram_id = ?
              AND attempted_at >= datetime('now', ?)
            """,
            (str(telegram_id), f"-{window_seconds} seconds"),
        ).fetchone()
        return row["cnt"]
    finally:
        conn.close()


def record_auth_attempt(telegram_id: str) -> None:
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO auth_attempts (telegram_id, attempted_at) VALUES (?, ?)",
                (str(telegram_id), now_utc_iso()),
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

def insert_expense(
    paid_by_user_id: int,
    amount: float,
    currency: str,
    amount_sgd: float,
    exchange_rate: float,
    category: str,
    description: str,
    split_method: str,
    group_chat_id: str,
    trip_id: Optional[int] = None,
) -> int:
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO expenses
                    (paid_by_user_id, amount, currency, amount_sgd, exchange_rate,
                     category, description, split_method, created_at, group_chat_id, trip_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    paid_by_user_id, amount, currency, amount_sgd, exchange_rate,
                    category, description, split_method, now_utc_iso(), str(group_chat_id),
                    trip_id,
                ),
            )
        return cur.lastrowid
    finally:
        conn.close()


def insert_expense_splits(expense_id: int, splits: list[tuple[int, float]]) -> None:
    """splits: list of (user_id, amount_sgd)"""
    conn = get_connection()
    try:
        with conn:
            conn.executemany(
                "INSERT INTO expense_splits (expense_id, user_id, amount_sgd) VALUES (?, ?, ?)",
                [(expense_id, uid, amt) for uid, amt in splits],
            )
    finally:
        conn.close()


def get_expenses_for_group(
    group_chat_id: str,
    since_iso: Optional[str] = None,
    trip_id: Optional[int] = None,
) -> list:
    conn = get_connection()
    try:
        conditions = ["e.group_chat_id = ?"]
        params: list = [str(group_chat_id)]
        if since_iso:
            conditions.append("e.created_at >= ?")
            params.append(since_iso)
        if trip_id is not None:
            conditions.append("e.trip_id = ?")
            params.append(trip_id)
        where = " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT e.*, u.display_name AS paid_by_name "
            f"FROM expenses e JOIN users u ON u.id = e.paid_by_user_id "
            f"WHERE {where} ORDER BY e.created_at DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_expense_by_id(expense_id: int, group_chat_id: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT e.*, u.display_name AS paid_by_name
            FROM expenses e
            JOIN users u ON u.id = e.paid_by_user_id
            WHERE e.id = ? AND e.group_chat_id = ?
            """,
            (expense_id, str(group_chat_id)),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_expense(expense_id: int, group_chat_id: str) -> bool:
    """Delete an expense and its splits. Returns True if a row was deleted."""
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "DELETE FROM expense_splits WHERE expense_id = ?",
                (expense_id,),
            )
            cur = conn.execute(
                "DELETE FROM expenses WHERE id = ? AND group_chat_id = ?",
                (expense_id, str(group_chat_id)),
            )
        return cur.rowcount > 0
    finally:
        conn.close()


def get_orphan_expenses(group_chat_id: str, limit: int = 100) -> list:
    """Return expenses with no trip association (trip_id IS NULL)."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT e.id, e.description, e.amount, e.currency, e.amount_sgd, "
            "e.category, e.created_at, u.display_name AS paid_by_name "
            "FROM expenses e JOIN users u ON u.id = e.paid_by_user_id "
            "WHERE e.group_chat_id = ? AND e.trip_id IS NULL "
            "ORDER BY e.created_at DESC LIMIT ?",
            (str(group_chat_id), limit),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_recent_expenses_for_group(
    group_chat_id: str,
    limit: int = 10,
    trip_id: Optional[int] = None,
) -> list:
    conn = get_connection()
    try:
        conditions = ["e.group_chat_id = ?"]
        params: list = [str(group_chat_id)]
        if trip_id is not None:
            conditions.append("e.trip_id = ?")
            params.append(trip_id)
        where = " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT e.id, e.description, e.amount, e.currency, e.amount_sgd, "
            f"e.category, e.created_at, u.display_name AS paid_by_name "
            f"FROM expenses e JOIN users u ON u.id = e.paid_by_user_id "
            f"WHERE {where} ORDER BY e.created_at DESC LIMIT ?",
            params + [limit],
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_expenses_by_category(group_chat_id: str, trip_id: Optional[int] = None) -> list:
    conn = get_connection()
    try:
        conditions = ["group_chat_id = ?"]
        params: list = [str(group_chat_id)]
        if trip_id is not None:
            conditions.append("trip_id = ?")
            params.append(trip_id)
        where = " AND ".join(conditions)
        rows = conn.execute(
            f"SELECT category, SUM(amount_sgd) AS total_sgd, COUNT(*) AS count "
            f"FROM expenses WHERE {where} GROUP BY category ORDER BY total_sgd DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Settlements
# ---------------------------------------------------------------------------

def insert_settlement(
    from_user_id: int,
    to_user_id: int,
    amount_sgd: float,
    group_chat_id: str,
    trip_id: Optional[int] = None,
) -> int:
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO settlements (from_user_id, to_user_id, amount_sgd, created_at, group_chat_id, trip_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (from_user_id, to_user_id, amount_sgd, now_utc_iso(), str(group_chat_id), trip_id),
            )
        return cur.lastrowid
    finally:
        conn.close()


def get_balance_data(group_chat_id: str, trip_id: Optional[int] = None) -> dict:
    """Return raw aggregates needed for net balance calculation, scoped to a trip."""
    conn = get_connection()
    try:
        gid = str(group_chat_id)
        exp_filter = "group_chat_id = ? AND trip_id = ?" if trip_id else "group_chat_id = ?"
        exp_params_single = (gid, trip_id) if trip_id else (gid,)
        stl_filter = "group_chat_id = ? AND trip_id = ?" if trip_id else "group_chat_id = ?"
        stl_params = (gid, trip_id) if trip_id else (gid,)

        paid = conn.execute(
            f"SELECT paid_by_user_id AS user_id, SUM(amount_sgd) AS total "
            f"FROM expenses WHERE {exp_filter} GROUP BY paid_by_user_id",
            exp_params_single,
        ).fetchall()

        owed = conn.execute(
            f"SELECT es.user_id, SUM(es.amount_sgd) AS total "
            f"FROM expense_splits es JOIN expenses e ON e.id = es.expense_id "
            f"WHERE e.{exp_filter} GROUP BY es.user_id",
            exp_params_single,
        ).fetchall()

        sent = conn.execute(
            f"SELECT from_user_id AS user_id, SUM(amount_sgd) AS total "
            f"FROM settlements WHERE {stl_filter} GROUP BY from_user_id",
            stl_params,
        ).fetchall()

        received = conn.execute(
            f"SELECT to_user_id AS user_id, SUM(amount_sgd) AS total "
            f"FROM settlements WHERE {stl_filter} GROUP BY to_user_id",
            stl_params,
        ).fetchall()

        users = conn.execute(
            f"SELECT DISTINCT u.id, u.display_name FROM users u "
            f"WHERE u.id IN ("
            f"  SELECT paid_by_user_id FROM expenses WHERE {exp_filter} "
            f"  UNION "
            f"  SELECT es.user_id FROM expense_splits es "
            f"  JOIN expenses e ON e.id = es.expense_id WHERE e.{exp_filter}"
            f")",
            exp_params_single + exp_params_single,
        ).fetchall()

        return {
            "paid": {r["user_id"]: r["total"] for r in paid},
            "owed": {r["user_id"]: r["total"] for r in owed},
            "sent": {r["user_id"]: r["total"] for r in sent},
            "received": {r["user_id"]: r["total"] for r in received},
            "users": {r["id"]: r["display_name"] for r in users},
        }
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Trips
# ---------------------------------------------------------------------------

def create_trip(group_chat_id: str, name: str, default_currency: str) -> int:
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO trips (group_chat_id, name, default_currency, started_at)
                VALUES (?, ?, ?, ?)
                """,
                (str(group_chat_id), name, default_currency.upper(), now_utc_iso()),
            )
        return cur.lastrowid
    finally:
        conn.close()


def end_trip(trip_id: int) -> bool:
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE trips SET ended_at = ? WHERE id = ? AND ended_at IS NULL",
                (now_utc_iso(), trip_id),
            )
        return cur.rowcount > 0
    finally:
        conn.close()


def get_active_trip(group_chat_id: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM trips WHERE group_chat_id = ? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            (str(group_chat_id),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_all_trips(group_chat_id: str) -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT t.*, COUNT(e.id) AS expense_count, COALESCE(SUM(e.amount_sgd), 0) AS total_sgd
            FROM trips t
            LEFT JOIN expenses e ON e.trip_id = t.id
            WHERE t.group_chat_id = ?
            GROUP BY t.id
            ORDER BY t.started_at DESC
            """,
            (str(group_chat_id),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_trip_by_id(trip_id: int, group_chat_id: str) -> Optional[dict]:
    """Return trip row with expense_count and total_sgd aggregates."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT t.*, COUNT(e.id) AS expense_count, COALESCE(SUM(e.amount_sgd), 0) AS total_sgd
            FROM trips t
            LEFT JOIN expenses e ON e.trip_id = t.id
            WHERE t.id = ? AND t.group_chat_id = ?
            GROUP BY t.id
            """,
            (trip_id, str(group_chat_id)),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_trip_by_name(group_chat_id: str, name: str) -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM trips WHERE group_chat_id = ? AND LOWER(name) = LOWER(?)",
            (str(group_chat_id), name),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def delete_trip(trip_id: int, group_chat_id: str) -> bool:
    """Delete a trip and disassociate its expenses (sets trip_id to NULL).
    Returns True if the trip was found and deleted."""
    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "UPDATE expenses SET trip_id = NULL WHERE trip_id = ?",
                (trip_id,),
            )
            conn.execute(
                "UPDATE settlements SET trip_id = NULL WHERE trip_id = ?",
                (trip_id,),
            )
            cur = conn.execute(
                "DELETE FROM trips WHERE id = ? AND group_chat_id = ?",
                (trip_id, str(group_chat_id)),
            )
        return cur.rowcount > 0
    finally:
        conn.close()


def add_trip_participants(trip_id: int, user_ids: list) -> None:
    """Insert participants for a trip. Silently ignores duplicates."""
    conn = get_connection()
    try:
        with conn:
            conn.executemany(
                "INSERT OR IGNORE INTO trip_participants (trip_id, user_id) VALUES (?, ?)",
                [(trip_id, uid) for uid in user_ids],
            )
    finally:
        conn.close()


def get_trip_participants(trip_id: int) -> list:
    """Return all users participating in a trip."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT u.id, u.telegram_id, u.display_name, u.is_guest
            FROM trip_participants tp
            JOIN users u ON u.id = tp.user_id
            WHERE tp.trip_id = ?
            ORDER BY u.is_guest, u.display_name
            """,
            (trip_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_expenses_for_trip(trip_id: int) -> list:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT e.*, u.display_name AS paid_by_name
            FROM expenses e
            JOIN users u ON u.id = e.paid_by_user_id
            WHERE e.trip_id = ?
            ORDER BY e.created_at ASC
            """,
            (trip_id,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
