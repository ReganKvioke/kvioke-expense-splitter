import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.db import queries
from bot.db.database import run_in_executor
from bot.middleware.auth import require_auth
from bot.services.balances import compute_net_balances
from bot.utils.format import fmt_sgd

logger = logging.getLogger(__name__)


@require_auth
async def cmd_settle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    group_chat_id = str(update.effective_chat.id)

    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)
    if not active_trip:
        await update.message.reply_text(
            "⛔ No active trip. Use /tripstart <name> [currency] to begin a trip first."
        )
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: /settle @username <amount>\nExample: /settle @alice 25"
        )
        return

    target_arg, amount_arg = context.args

    try:
        amount = float(amount_arg)
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please enter a number.")
        return

    if amount <= 0:
        await update.message.reply_text("❌ Amount must be positive.")
        return

    # Auto-register the sender
    display_name = user.username or user.first_name or str(user.id)
    from_user_id = await run_in_executor(queries.upsert_user, str(user.id), display_name)

    # Find target user
    target_name = target_arg.lstrip("@")
    to_user = await run_in_executor(queries.get_user_by_username, target_name)

    if to_user is None:
        await update.message.reply_text(
            f"❌ User @{target_name} not found. They must have interacted with the bot first."
        )
        return

    to_user_id = to_user["id"]

    if from_user_id == to_user_id:
        await update.message.reply_text("❌ You cannot settle with yourself.")
        return

    # Check the sender's net balance — block over-settling
    balance_data = await run_in_executor(queries.get_balance_data, group_chat_id, active_trip["id"])
    net = compute_net_balances(balance_data)
    sender_net = net.get(from_user_id, 0.0)

    if sender_net >= -0.01:
        await update.message.reply_text(
            "❌ You have no outstanding balance to settle in this trip."
        )
        return

    max_settle = round(-sender_net, 2)
    if round(amount, 2) > max_settle:
        await update.message.reply_text(
            f"❌ You only owe {fmt_sgd(max_settle)} in total for this trip. "
            f"Cannot settle {fmt_sgd(amount)}."
        )
        return

    try:
        await run_in_executor(
            queries.insert_settlement,
            from_user_id, to_user_id, round(amount, 2), group_chat_id, active_trip["id"],
        )
    except Exception as exc:
        logger.error("Failed to insert settlement: %s", exc)
        await update.message.reply_text("❌ Could not record settlement. Please try again.")
        return

    await update.message.reply_text(
        f"✅ Recorded: {display_name} paid {to_user['display_name']} {fmt_sgd(amount)}."
    )
