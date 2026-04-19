import asyncio
import logging
import os
import sqlite3
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_default_db = Path(__file__).parent.parent.parent / "expense_bot.db"
DB_PATH = Path(os.getenv("DB_PATH", str(_default_db)))


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


async def run_in_executor(func: Callable, *args: Any) -> Any:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, func, *args)
