from telegram import Update
from telegram.ext import ContextTypes
from bot.middleware.auth import require_auth

HELP_TEXT = (
    "🤖 *KviokeExpenseSplitter Bot*\n\n"
    "*Commands:*\n\n"
    "/add — Log a new shared expense\n"
    "  Starts a guided multi-step flow to record who paid, how much, and how to split.\n\n"
    "/quickadd [@payer] <amount> [currency] <category> <description>\n"
    "  Log an expense in one line. Split is always equal.\n"
    "  Examples:\n"
    "    /quickadd 50 food lunch at hawker\n"
    "    /quickadd 50 USD food lunch at hawker\n"
    "    /quickadd @Brandeline 50 USD food lunch\n\n"
    "/balances — Show who owes whom\n"
    "  Displays net balances for everyone in this group and suggests minimal transfers.\n\n"
    "/summary [period] — View spending breakdown\n"
    "  Periods: today, week (default), month, category\n"
    "  Example: /summary month\n\n"
    "/settle @username amount — Record a payment\n"
    "  Example: /settle @alice 25\n\n"
    "/delete — Delete an expense\n"
    "  Shows expenses for the active trip, or all expenses if no trip is active.\n\n"
    "/tripstart <name> [currency] — Start a new trip\n"
    "  Sets the default currency for /quickadd.\n"
    "  Example: /tripstart Japan Trip JPY\n\n"
    "/tripend — End the current active trip\n\n"
    "/tripsummary [name] — View trip expenses\n"
    "  No name → list all trips. With name → full expense list.\n"
    "  Example: /tripsummary Japan Trip\n\n"
    "/help — Show this message\n\n"
    "/start <password> — Authenticate with the bot\n\n"
    "*Admin only:*\n"
    "/users — List all authorized users\n"
    "/revoke @username — Remove a user's access\n"
    "/tripdelete — Delete a trip (expenses kept but unlinked)\n"
    "/orphans — View and delete expenses not linked to any trip\n"
    "/guestdelete — Remove a guest user (blocked if they have linked expenses)"
)


@require_auth
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(HELP_TEXT, parse_mode="Markdown")
