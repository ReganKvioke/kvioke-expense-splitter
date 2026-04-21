"""Single-confirm /undo command — delete the most recently added expense."""
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
)

from bot.db import queries
from bot.db.database import run_in_executor
from bot.middleware.auth import require_auth
from bot.utils.format import fmt_amount, fmt_category, fmt_sgd

logger = logging.getLogger(__name__)

UNDO_CONFIRM = 0


def _undo_keyboard(expense_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("↩️ Undo", callback_data=f"undo_confirm:{expense_id}"),
            InlineKeyboardButton("❌ Keep", callback_data="undo_cancel"),
        ]
    ])


@require_auth
async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_chat_id = str(update.effective_chat.id)
    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)
    trip_id = active_trip["id"] if active_trip else None

    context.user_data.clear()

    expenses = await run_in_executor(
        queries.get_recent_expenses_for_group, group_chat_id, 1, trip_id
    )

    if not expenses:
        await update.message.reply_text("No recent expenses found to undo.")
        return ConversationHandler.END

    expense = expenses[0]
    context.user_data["undo_expense"] = expense

    trip_label = f" in *{active_trip['name']}*" if active_trip else ""
    text = (
        f"Last expense{trip_label}:\n\n"
        f"📝 {expense['description']}\n"
        f"💰 {fmt_amount(expense['amount'], expense['currency'])} ({fmt_sgd(expense['amount_sgd'])})\n"
        f"🏷️ {fmt_category(expense['category'])}\n"
        f"👤 Paid by {expense['paid_by_name']}\n\n"
        "Undo this expense?"
    )
    await update.message.reply_text(
        text, reply_markup=_undo_keyboard(expense["id"]), parse_mode="Markdown"
    )
    return UNDO_CONFIRM


async def handle_undo_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    expense_id = int(query.data.split(":", 1)[1])
    group_chat_id = str(update.effective_chat.id)
    expense = context.user_data.get("undo_expense", {})

    try:
        deleted = await run_in_executor(queries.delete_expense, expense_id, group_chat_id)
    except Exception as exc:
        logger.error("Failed to undo expense %s: %s", expense_id, exc)
        await query.edit_message_text("❌ Failed to delete expense. Please try again.")
        return ConversationHandler.END

    if deleted:
        await query.edit_message_text(
            f"✅ Undone: *{expense.get('description', '')}* — "
            f"{fmt_amount(expense.get('amount', 0), expense.get('currency', 'SGD'))} removed.",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text("❌ Expense not found or already deleted.")

    context.user_data.clear()
    return ConversationHandler.END


async def handle_undo_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Kept. No changes made.")
    context.user_data.clear()
    return ConversationHandler.END


def build_undo_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("undo", cmd_undo)],
        states={
            UNDO_CONFIRM: [
                CallbackQueryHandler(handle_undo_confirm, pattern=r"^undo_confirm:"),
                CallbackQueryHandler(handle_undo_cancel, pattern=r"^undo_cancel$"),
            ],
        },
        fallbacks=[],
        per_user=True,
        per_chat=True,
    )
