from telegram import Update
from telegram.ext import ContextTypes
from bot.middleware.auth import require_auth

HELP_TEXT = (
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
    "/exporthtml — Download an interactive HTML expense dashboard\n\n"
    "*Trips*\n"
    "/tripstart `<name> [currency]` — Start a new trip\n"
    "/tripend — End the active trip\n"
    "/tripsummary `[name]` — View trip expenses\n\n"
    "*Account*\n"
    "/start `<password>` — Authenticate\n"
    "/help — Show this message\n\n"
    "*Admin*\n"
    "/users — List authorized users\n"
    "/revoke `@user` — Revoke access\n"
    "/tripdelete — Delete a trip\n"
    "/tripdeleteforce — Permanently delete a trip and all its records\n"
    "/orphans — Manage unlinked expenses\n"
    "/guestdelete — Remove a guest user"
)


@require_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")
