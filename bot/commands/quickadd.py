"""Single-line /quickadd command.

Syntax:
    /quickadd [@payer] <amount> [currency] <category> <description>

Examples:
    /quickadd 50 food lunch at hawker centre
    /quickadd 50 USD food lunch at hawker centre
    /quickadd @Brandeline 50 USD food lunch at hawker centre
    /quickadd @Brandeline 5000 JPY flight airport transfer

Rules:
- @payer is optional; defaults to the user running the command.
- currency is optional; defaults to SGD.
- category must be one of the supported categories.
- description is everything after the category token.
- Split is always equal among all known group members.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.db import queries
from bot.db.database import run_in_executor
from bot.middleware.auth import require_auth
from bot.services.currency import convert_to_sgd
from bot.services.splitting import equal_split
from bot.utils.constants import CATEGORIES, SUPPORTED_CURRENCIES
from bot.utils.format import fmt_amount, fmt_category

logger = logging.getLogger(__name__)

_USAGE = (
    "Usage: /quickadd [@payer] <amount> [currency] <category> <description>\n\n"
    "Examples:\n"
    "  /quickadd 50 food lunch at hawker\n"
    "  /quickadd 50 USD food lunch at hawker\n"
    "  /quickadd @Brandeline 50 USD food lunch at hawker\n\n"
    f"Categories: {', '.join(CATEGORIES)}"
)


def _parse_args(tokens: list[str]) -> dict | None:
    """Parse token list into a dict with keys: payer_name, amount, currency, category, description.

    Returns None if tokens are invalid.
    payer_name is None when the payer is the command sender.
    """
    idx = 0

    # Optional @payer
    payer_name: str | None = None
    if tokens and tokens[0].startswith("@"):
        payer_name = tokens[0].lstrip("@")
        idx += 1

    if idx >= len(tokens):
        return None

    # Amount
    try:
        amount = float(tokens[idx])
    except ValueError:
        return None
    if amount <= 0:
        return None
    idx += 1

    if idx >= len(tokens):
        return None

    # Optional currency
    currency = "SGD"
    currency_explicit = False
    if tokens[idx].upper() in SUPPORTED_CURRENCIES:
        currency = tokens[idx].upper()
        currency_explicit = True
        idx += 1

    if idx >= len(tokens):
        return None

    # Category
    cat_token = tokens[idx].lower()
    if cat_token not in CATEGORIES:
        return None
    category = cat_token
    idx += 1

    # Description (everything remaining)
    if idx >= len(tokens):
        return None
    description = " ".join(tokens[idx:])

    return {
        "payer_name": payer_name,
        "amount": amount,
        "currency": currency,
        "currency_explicit": currency_explicit,
        "category": category,
        "description": description,
    }


@require_auth
async def cmd_quickadd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    tokens = context.args or []
    parsed = _parse_args(tokens)

    if not parsed:
        await update.message.reply_text(f"❌ Invalid format.\n\n{_USAGE}")
        return

    group_chat_id = str(update.effective_chat.id)
    sender = update.effective_user
    sender_display = sender.username or sender.first_name or str(sender.id)

    # Resolve payer
    if parsed["payer_name"] is None:
        payer_db_id = await run_in_executor(queries.upsert_user, str(sender.id), sender_display)
        payer_display = sender_display
    else:
        target = await run_in_executor(queries.get_user_by_username, parsed["payer_name"])
        if target is None:
            await update.message.reply_text(
                f"❌ Unknown user @{parsed['payer_name']}. "
                "They must have used the bot at least once in this group."
            )
            return
        payer_db_id = target["id"]
        payer_display = target["display_name"]

    # Require an active trip
    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)
    if not active_trip:
        await update.message.reply_text(
            "⛔ No active trip. Use /tripstart <name> [currency] to begin a trip first."
        )
        return

    # Use trip's default currency if the user didn't explicitly type one
    if not parsed["currency_explicit"]:
        parsed["currency"] = active_trip["default_currency"]

    trip_id = active_trip["id"]

    # Currency conversion
    amount_sgd, exchange_rate = await convert_to_sgd(parsed["amount"], parsed["currency"])
    if amount_sgd is None:
        await update.message.reply_text(
            "❌ Could not fetch exchange rates right now. Please try again later."
        )
        return

    # Equal split among trip participants (fallback to group users if trip has none)
    group_users = await run_in_executor(queries.get_trip_participants, trip_id)
    if not group_users:
        group_users = await run_in_executor(queries.get_all_users_in_group, group_chat_id)
    # Ensure the payer is always in the split pool
    if not any(u["id"] == payer_db_id for u in group_users):
        group_users.append({"id": payer_db_id, "display_name": payer_display})

    user_ids = [u["id"] for u in group_users]
    splits = equal_split(amount_sgd, user_ids, payer_db_id)

    try:
        expense_id = await run_in_executor(
            queries.insert_expense,
            payer_db_id,
            parsed["amount"],
            parsed["currency"],
            amount_sgd,
            exchange_rate,
            parsed["category"],
            parsed["description"],
            "equal",
            group_chat_id,
            trip_id,
        )
        await run_in_executor(queries.insert_expense_splits, expense_id, splits)
    except Exception as exc:
        logger.error("quickadd failed: %s", exc)
        await update.message.reply_text("❌ Failed to save expense. Please try again.")
        return

    cat_label = fmt_category(parsed["category"])
    trip_note = f" · 📍 {active_trip['name']}" if active_trip else ""
    await update.message.reply_text(
        f"✅ ({cat_label}) {parsed['description']} -- {fmt_amount(parsed['amount'], parsed['currency'])}"
        f"\nPaid by: {payer_display} · split equally{trip_note}"
    )
