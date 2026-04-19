"""Authentication middleware and /start, /revoke, /users command handlers."""
import asyncio
import logging
import os
from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from bot.db import queries
from bot.utils.constants import RATE_LIMIT_MAX_ATTEMPTS, RATE_LIMIT_WINDOW_SECONDS
from bot.utils.format import fmt_datetime

logger = logging.getLogger(__name__)


def get_admin_ids() -> list[str]:
    raw = os.getenv("ADMIN_USER_IDS", "")
    return [x.strip() for x in raw.split(",") if x.strip()]


def require_auth(handler: Callable) -> Callable:
    """Decorator that blocks unauthorized users before running the handler."""
    @wraps(handler)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user = update.effective_user
        if user is None:
            return

        admin_ids = get_admin_ids()
        loop = asyncio.get_running_loop()
        authorized = await loop.run_in_executor(None, queries.is_authorized, str(user.id), admin_ids)
        if not authorized:
            logger.warning(
                "Unauthorized access attempt by user_id=%s username=%s",
                user.id, user.username,
            )
            await update.effective_message.reply_text(
                "⛔ You don't have access. Use /start <password> to authenticate."
            )
            return
        return await handler(update, context, *args, **kwargs)
    return wrapper


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    admin_ids = get_admin_ids()

    loop = asyncio.get_running_loop()

    if await loop.run_in_executor(None, queries.is_authorized, str(user.id), admin_ids):
        await update.message.reply_text(
            f"👋 Welcome back, {user.first_name}! You're already authorized.\n"
            "Use /help to see available commands."
        )
        return

    password = os.getenv("BOT_PASSWORD", "")
    provided = " ".join(context.args) if context.args else ""

    # Rate limiting
    attempts = await loop.run_in_executor(
        None, queries.count_recent_auth_attempts, str(user.id), RATE_LIMIT_WINDOW_SECONDS
    )
    if attempts >= RATE_LIMIT_MAX_ATTEMPTS:
        await update.message.reply_text("⛔ Too many attempts. Try again later.")
        return

    if not provided:
        await update.message.reply_text("Please provide the password: /start <password>")
        return

    await loop.run_in_executor(None, queries.record_auth_attempt, str(user.id))

    if provided != password:
        remaining = RATE_LIMIT_MAX_ATTEMPTS - attempts - 1
        await update.message.reply_text(
            f"❌ Incorrect password. {remaining} attempt(s) remaining before lockout."
        )
        return

    await loop.run_in_executor(None, queries.authorize_user, str(user.id), "password")
    # Also register them in users table
    display_name = user.username or user.first_name or str(user.id)
    await loop.run_in_executor(None, queries.upsert_user, str(user.id), display_name)

    await update.message.reply_text(
        f"✅ Access granted! Welcome, {user.first_name}!\n"
        "Use /help to see available commands."
    )


async def cmd_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    admin_ids = get_admin_ids()

    if str(user.id) not in admin_ids:
        await update.message.reply_text("⛔ This command is for admins only.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /revoke @username_or_id")
        return

    target = context.args[0].lstrip("@")
    loop = asyncio.get_running_loop()
    # Try to find by display_name first, then as raw telegram_id
    target_user = await loop.run_in_executor(None, queries.get_user_by_username, target)
    if target_user:
        target_id = str(target_user["telegram_id"])
    else:
        target_id = target

    revoked = await loop.run_in_executor(None, queries.revoke_user, target_id)
    if revoked:
        await update.message.reply_text(f"✅ Access revoked for {context.args[0]}.")
    else:
        await update.message.reply_text(f"ℹ️ User {context.args[0]} was not found in authorized list.")


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    admin_ids = get_admin_ids()

    if str(user.id) not in admin_ids:
        await update.message.reply_text("⛔ This command is for admins only.")
        return

    authorized = await asyncio.get_running_loop().run_in_executor(None, queries.get_all_authorized_users)
    if not authorized:
        await update.message.reply_text("No authorized users yet.")
        return

    lines = ["👥 Authorized users:\n"]
    for u in authorized:
        lines.append(
            f"• {u['telegram_id']} — via {u['authorized_by']} on {fmt_datetime(u['authorized_at'])}"
        )
    await update.message.reply_text("\n".join(lines))
