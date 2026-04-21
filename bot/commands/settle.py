"""Settle command.

Two modes:
  /settle @username amount  — legacy one-liner (unchanged behaviour)
  /settle                   — interactive flow: shows who you owe with pre-filled amounts
"""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from bot.db import queries
from bot.db.database import run_in_executor
from bot.middleware.auth import require_auth
from bot.services.balances import compute_net_balances, simplify_debts
from bot.utils.format import fmt_sgd

logger = logging.getLogger(__name__)

SL_PICK_PERSON, SL_CONFIRM_AMOUNT, SL_CUSTOM_AMOUNT = range(3)


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def _pick_keyboard(my_transfers: list, names: dict) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            f"👤 {names.get(to_id, str(to_id))} (you owe {fmt_sgd(amount)})",
            callback_data=f"sl_person:{to_id}",
        )]
        for _, to_id, amount in my_transfers
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="sl_cancel")])
    return InlineKeyboardMarkup(buttons)


def _confirm_keyboard(suggested: float) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✅ Confirm {fmt_sgd(suggested)}", callback_data="sl_confirm"),
            InlineKeyboardButton("✏️ Custom amount", callback_data="sl_custom"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="sl_cancel")],
    ])


# ---------------------------------------------------------------------------
# Shared helper
# ---------------------------------------------------------------------------

async def _record_settlement(context: ContextTypes.DEFAULT_TYPE, amount: float) -> tuple[bool, str]:
    from_user_id = context.user_data["sl_from_id"]
    to_user_id = context.user_data["sl_to_id"]
    from_name = context.user_data["sl_from_name"]
    to_name = context.user_data["sl_to_name"]
    trip_id = context.user_data["sl_trip_id"]
    group_chat_id = context.user_data["sl_group_chat_id"]

    try:
        await run_in_executor(
            queries.insert_settlement,
            from_user_id, to_user_id, round(amount, 2), group_chat_id, trip_id,
        )
        context.user_data.clear()
        return True, f"✅ Recorded: {from_name} paid {to_name} {fmt_sgd(amount)}."
    except Exception as exc:
        logger.error("Failed to insert settlement: %s", exc)
        return False, "❌ Could not record settlement. Please try again."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

@require_auth
async def cmd_settle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    group_chat_id = str(update.effective_chat.id)

    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)
    if not active_trip:
        await update.message.reply_text(
            "⛔ No active trip. Use /tripstart <name> [currency] to begin a trip first."
        )
        return ConversationHandler.END

    # --- Legacy syntax: /settle @user amount ---
    if context.args:
        if len(context.args) != 2:
            await update.message.reply_text(
                "Usage: /settle @username <amount>\nOr just /settle to pick interactively."
            )
            return ConversationHandler.END

        target_arg, amount_arg = context.args

        try:
            amount = float(amount_arg)
        except ValueError:
            await update.message.reply_text("❌ Invalid amount. Please enter a number.")
            return ConversationHandler.END

        if amount <= 0:
            await update.message.reply_text("❌ Amount must be positive.")
            return ConversationHandler.END

        display_name = user.username or user.first_name or str(user.id)
        from_user_id = await run_in_executor(queries.upsert_user, str(user.id), display_name)

        target_name = target_arg.lstrip("@")
        to_user = await run_in_executor(queries.get_user_by_username, target_name)
        if to_user is None:
            await update.message.reply_text(
                f"❌ User @{target_name} not found. They must have interacted with the bot first."
            )
            return ConversationHandler.END

        to_user_id = to_user["id"]
        if from_user_id == to_user_id:
            await update.message.reply_text("❌ You cannot settle with yourself.")
            return ConversationHandler.END

        balance_data = await run_in_executor(
            queries.get_balance_data, group_chat_id, active_trip["id"]
        )
        net = compute_net_balances(balance_data)
        sender_net = net.get(from_user_id, 0.0)

        if sender_net >= -0.01:
            await update.message.reply_text(
                "❌ You have no outstanding balance to settle in this trip."
            )
            return ConversationHandler.END

        # Validate that the recipient is actually someone this sender owes
        all_transfers = simplify_debts(net)
        valid_recipients = {t: a for f, t, a in all_transfers if f == from_user_id}
        if to_user_id not in valid_recipients:
            names = balance_data["users"]
            valid_names = ", ".join(
                f"@{names.get(tid, str(tid))}" for tid in valid_recipients
            )
            await update.message.reply_text(
                f"❌ You don't owe @{to_user['display_name']} in this trip.\n"
                f"You should settle with: {valid_names or 'nobody (all clear!)'}.\n"
                f"Use /settle to pick interactively."
            )
            return ConversationHandler.END

        max_settle = round(-sender_net, 2)
        if round(amount, 2) > max_settle:
            await update.message.reply_text(
                f"❌ You only owe {fmt_sgd(max_settle)} in total for this trip. "
                f"Cannot settle {fmt_sgd(amount)}."
            )
            return ConversationHandler.END

        try:
            await run_in_executor(
                queries.insert_settlement,
                from_user_id, to_user_id, round(amount, 2), group_chat_id, active_trip["id"],
            )
        except Exception as exc:
            logger.error("Failed to insert settlement: %s", exc)
            await update.message.reply_text("❌ Could not record settlement. Please try again.")
            return ConversationHandler.END

        await update.message.reply_text(
            f"✅ Recorded: {display_name} paid {to_user['display_name']} {fmt_sgd(amount)}."
        )
        return ConversationHandler.END

    # --- Interactive flow: /settle (no args) ---
    display_name = user.username or user.first_name or str(user.id)
    from_user_id = await run_in_executor(queries.upsert_user, str(user.id), display_name)

    balance_data = await run_in_executor(
        queries.get_balance_data, group_chat_id, active_trip["id"]
    )
    net = compute_net_balances(balance_data)
    all_transfers = simplify_debts(net)
    my_transfers = [(f, t, a) for f, t, a in all_transfers if f == from_user_id]

    if not my_transfers:
        await update.message.reply_text(
            "✅ You have no outstanding balances to settle in this trip."
        )
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["sl_trip_id"] = active_trip["id"]
    context.user_data["sl_group_chat_id"] = group_chat_id
    context.user_data["sl_from_id"] = from_user_id
    context.user_data["sl_from_name"] = display_name
    # Map to_user_id → suggested amount for quick lookup
    context.user_data["sl_transfers"] = {t: a for _, t, a in my_transfers}

    names = balance_data["users"]
    await update.message.reply_text(
        f"💳 Who are you settling with? *(Trip: {active_trip['name']})*",
        reply_markup=_pick_keyboard(my_transfers, names),
        parse_mode="Markdown",
    )
    return SL_PICK_PERSON


# ---------------------------------------------------------------------------
# Interactive flow handlers
# ---------------------------------------------------------------------------

async def handle_sl_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    to_user_id = int(query.data.split(":", 1)[1])
    transfers = context.user_data.get("sl_transfers", {})
    suggested = transfers.get(to_user_id)

    if suggested is None:
        await query.edit_message_text("❌ Selection expired. Please run /settle again.")
        return ConversationHandler.END

    to_user = await run_in_executor(queries.get_user_by_id, to_user_id)
    to_name = to_user["display_name"] if to_user else str(to_user_id)

    context.user_data["sl_to_id"] = to_user_id
    context.user_data["sl_to_name"] = to_name
    context.user_data["sl_suggested"] = suggested

    await query.edit_message_text(
        f"Settle {fmt_sgd(suggested)} with *{to_name}*?",
        reply_markup=_confirm_keyboard(suggested),
        parse_mode="Markdown",
    )
    return SL_CONFIRM_AMOUNT


async def handle_sl_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    amount = context.user_data.get("sl_suggested", 0.0)
    success, msg = await _record_settlement(context, amount)
    await query.edit_message_text(msg)
    return ConversationHandler.END


async def handle_sl_custom_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    suggested = context.user_data.get("sl_suggested", 0.0)
    to_name = context.user_data.get("sl_to_name", "")
    await query.edit_message_text(
        f"Enter the amount to settle with *{to_name}* (max {fmt_sgd(suggested)}):",
        parse_mode="Markdown",
    )
    return SL_CUSTOM_AMOUNT


async def handle_sl_custom_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()

    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text("❌ Invalid amount. Please enter a number.")
        return SL_CUSTOM_AMOUNT

    if amount <= 0:
        await update.message.reply_text("❌ Amount must be positive.")
        return SL_CUSTOM_AMOUNT

    suggested = context.user_data.get("sl_suggested", 0.0)
    if round(amount, 2) > round(suggested, 2):
        await update.message.reply_text(
            f"❌ You can settle at most {fmt_sgd(suggested)}. Please enter a smaller amount."
        )
        return SL_CUSTOM_AMOUNT

    success, msg = await _record_settlement(context, amount)
    await update.message.reply_text(msg)
    return ConversationHandler.END


async def handle_sl_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


async def handle_sl_unexpected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Please use the buttons above, or /settle to start over.")
    return None


# ---------------------------------------------------------------------------
# Handler builder
# ---------------------------------------------------------------------------

def build_settle_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("settle", cmd_settle)],
        states={
            SL_PICK_PERSON: [
                CallbackQueryHandler(handle_sl_pick, pattern=r"^sl_person:"),
                CallbackQueryHandler(handle_sl_cancel, pattern=r"^sl_cancel$"),
            ],
            SL_CONFIRM_AMOUNT: [
                CallbackQueryHandler(handle_sl_confirm, pattern=r"^sl_confirm$"),
                CallbackQueryHandler(handle_sl_custom_start, pattern=r"^sl_custom$"),
                CallbackQueryHandler(handle_sl_cancel, pattern=r"^sl_cancel$"),
            ],
            SL_CUSTOM_AMOUNT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sl_custom_amount),
            ],
        },
        fallbacks=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sl_unexpected),
            CallbackQueryHandler(handle_sl_cancel, pattern=r"^sl_cancel$"),
        ],
        per_user=True,
        per_chat=True,
    )
