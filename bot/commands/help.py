import os

from telegram import Update
from telegram.ext import ContextTypes
from bot.middleware.auth import require_auth

_HELP_USER = (
    "🤖 *KviokeExpenseSplitter*\n\n"
    "*Expenses*\n"
    "/add — Log a shared expense \\(guided flow\\)\n"
    "/quickadd `[@payer] <amount> [currency] <category> <desc>` — One-line expense, equal split\n"
    "/undo — Remove the last expense\n"
    "/edit — Edit description or category\n"
    "/delete — Delete an expense\n\n"
    "*Balances & Settlements*\n"
    "/balances — Net positions and suggested transfers\n"
    "/settle `[@user amount]` — Record a payment \\(interactive or one-liner\\)\n"
    "/settlements — Settlement history for the active trip\n\n"
    "*Summary & Export*\n"
    "/summary `[today|week|month|category]` — Spending breakdown\n"
    "/me — Your personal stats for the active trip\n"
    "/exporthtml — Download an interactive HTML expense dashboard\n\n"
    "*Trips*\n"
    "/tripstart `<name> [currency]` — Start a new trip\n"
    "/tripjoin — Join the active trip\n"
    "/tripend — End the active trip\n"
    "/tripsummary `[name]` — View trip expenses\n\n"
    "*Account*\n"
    "/start `<password>` — Authenticate\n"
    "/help — Show this message"
)

_HELP_ADMIN_EXTRA = (
    "\n\n*Admin*\n"
    "/users — List authorized users\n"
    "/revoke `@user` — Revoke access\n"
    "/tripdelete — Delete a trip\n"
    "/tripdeleteforce — Permanently delete a trip and all its records\n"
    "/orphans — Manage unlinked expenses\n"
    "/guestdelete — Remove a guest user\n"
    "/guestmerge — Replace a guest user with a real account"
)


def _admin_ids() -> set[str]:
    raw = os.getenv("ADMIN_USER_IDS", "")
    return {s.strip() for s in raw.split(",") if s.strip()}


@require_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tg_id = str(update.effective_user.id)
    is_admin = tg_id in _admin_ids()
    text = _HELP_USER + (_HELP_ADMIN_EXTRA if is_admin else "")
    await update.message.reply_text(text, parse_mode="Markdown")
