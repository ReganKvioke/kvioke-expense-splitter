import sqlite3
import logging
from bot.db.database import get_connection

logger = logging.getLogger(__name__)

CREATE_USERS = """
CREATE TABLE IF NOT EXISTS users (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id  TEXT    NOT NULL UNIQUE,
    display_name TEXT    NOT NULL,
    is_guest     INTEGER NOT NULL DEFAULT 0
);
"""

CREATE_AUTHORIZED_USERS = """
CREATE TABLE IF NOT EXISTS authorized_users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id   TEXT    NOT NULL UNIQUE,
    authorized_at TEXT    NOT NULL,
    authorized_by TEXT    NOT NULL
);
"""

CREATE_EXPENSES = """
CREATE TABLE IF NOT EXISTS expenses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    paid_by_user_id INTEGER NOT NULL REFERENCES users(id),
    amount          REAL    NOT NULL,
    currency        TEXT    NOT NULL,
    amount_sgd      REAL    NOT NULL,
    exchange_rate   REAL    NOT NULL,
    category        TEXT    NOT NULL,
    description     TEXT    NOT NULL,
    split_method    TEXT    NOT NULL CHECK(split_method IN ('equal', 'discrete')),
    created_at      TEXT    NOT NULL,
    group_chat_id   TEXT    NOT NULL
);
"""

CREATE_EXPENSE_SPLITS = """
CREATE TABLE IF NOT EXISTS expense_splits (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    expense_id  INTEGER NOT NULL REFERENCES expenses(id),
    user_id     INTEGER NOT NULL REFERENCES users(id),
    amount_sgd  REAL    NOT NULL
);
"""

CREATE_SETTLEMENTS = """
CREATE TABLE IF NOT EXISTS settlements (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    from_user_id  INTEGER NOT NULL REFERENCES users(id),
    to_user_id    INTEGER NOT NULL REFERENCES users(id),
    amount_sgd    REAL    NOT NULL,
    created_at    TEXT    NOT NULL,
    group_chat_id TEXT    NOT NULL
);
"""

CREATE_AUTH_ATTEMPTS = """
CREATE TABLE IF NOT EXISTS auth_attempts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id TEXT    NOT NULL,
    attempted_at TEXT   NOT NULL
);
"""

CREATE_TRIPS = """
CREATE TABLE IF NOT EXISTS trips (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    group_chat_id    TEXT    NOT NULL,
    name             TEXT    NOT NULL,
    default_currency TEXT    NOT NULL DEFAULT 'SGD',
    started_at       TEXT    NOT NULL,
    ended_at         TEXT
);
"""

CREATE_TRIP_PARTICIPANTS = """
CREATE TABLE IF NOT EXISTS trip_participants (
    trip_id  INTEGER NOT NULL REFERENCES trips(id) ON DELETE CASCADE,
    user_id  INTEGER NOT NULL REFERENCES users(id),
    PRIMARY KEY (trip_id, user_id)
);
"""


def init_db() -> None:
    conn = get_connection()
    try:
        with conn:
            conn.execute(CREATE_USERS)
            conn.execute(CREATE_AUTHORIZED_USERS)
            conn.execute(CREATE_EXPENSES)
            conn.execute(CREATE_EXPENSE_SPLITS)
            conn.execute(CREATE_SETTLEMENTS)
            conn.execute(CREATE_AUTH_ATTEMPTS)
            conn.execute(CREATE_TRIPS)
            conn.execute(CREATE_TRIP_PARTICIPANTS)
            # Migration: add is_guest to users (no-op if column already exists)
            try:
                conn.execute(
                    "ALTER TABLE users ADD COLUMN is_guest INTEGER NOT NULL DEFAULT 0"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
            # Migration: add trip_id to expenses (no-op if column already exists)
            try:
                conn.execute(
                    "ALTER TABLE expenses ADD COLUMN trip_id INTEGER REFERENCES trips(id)"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
            # Migration: add trip_id to settlements (no-op if column already exists)
            try:
                conn.execute(
                    "ALTER TABLE settlements ADD COLUMN trip_id INTEGER REFERENCES trips(id)"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
            # Indexes for common query patterns
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_expenses_group_trip "
                "ON expenses(group_chat_id, trip_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_expenses_payer "
                "ON expenses(paid_by_user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_expense_splits_expense "
                "ON expense_splits(expense_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_expense_splits_user "
                "ON expense_splits(user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_settlements_group_trip "
                "ON settlements(group_chat_id, trip_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_settlements_from "
                "ON settlements(from_user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_settlements_to "
                "ON settlements(to_user_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trips_group "
                "ON trips(group_chat_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_trip_participants_trip "
                "ON trip_participants(trip_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_auth_attempts_lookup "
                "ON auth_attempts(telegram_id, attempted_at)"
            )
        logger.info("Database schema initialised")
    finally:
        conn.close()
