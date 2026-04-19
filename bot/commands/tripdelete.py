"""Two-step /tripdelete command: list trips → confirm → delete."""
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
from bot.middleware.auth import require_auth, get_admin_ids
from bot.utils.format import fmt_sgd, fmt_date

logger = logging.getLogger(__name__)

STATE_PICK, STATE_CONFIRM = range(2)


def _trip_list_keyboard(trips: list) -> InlineKeyboardMarkup:
    buttons = []
    for t in trips:
        status = "🟢" if t["ended_at"] is None else "🏁"
        label = f"{status} {t['name']} ({t['default_currency']}) · {fmt_date(t['started_at'])}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"tdel_pick:{t['id']}")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="tdel_cancel")])
    return InlineKeyboardMarkup(buttons)


def _confirm_keyboard(trip_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑 Yes, delete", callback_data=f"tdel_confirm:{trip_id}"),
            InlineKeyboardButton("◀ Back", callback_data="tdel_back"),
        ]
    ])


async def _show_list(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False) -> int:
    group_chat_id = str(update.effective_chat.id)

    trips = await run_in_executor(queries.get_all_trips, group_chat_id)

    if not trips:
        text = "No trips found in this group."
        if edit:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return ConversationHandler.END

    text = "🗺️ Select a trip to delete:"
    keyboard = _trip_list_keyboard(trips)

    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard)
    else:
        await update.message.reply_text(text, reply_markup=keyboard)

    return STATE_PICK


@require_auth
async def cmd_tripdelete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    if str(user.id) not in get_admin_ids():
        await update.message.reply_text("⛔ This command is for admins only.")
        return ConversationHandler.END

    context.user_data.clear()
    return await _show_list(update, context, edit=False)


async def handle_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    trip_id = int(query.data.split(":", 1)[1])
    group_chat_id = str(update.effective_chat.id)

    trip = await run_in_executor(queries.get_trip_by_id, trip_id, group_chat_id)
    if not trip:
        await query.edit_message_text("❌ Trip not found.")
        return ConversationHandler.END

    context.user_data["tdel_trip"] = trip

    status = "🟢 Active" if trip["ended_at"] is None else f"🏁 Ended {fmt_date(trip['ended_at'])}"
    text = (
        "⚠️ *Confirm trip deletion:*\n\n"
        f"Name: {trip['name']}\n"
        f"Currency: {trip['default_currency']}\n"
        f"Started: {fmt_date(trip['started_at'])}\n"
        f"Status: {status}\n"
        f"Expenses: {trip['expense_count']} · {fmt_sgd(trip['total_sgd'])}\n\n"
        "The trip record will be deleted. Expenses will be kept but unlinked from this trip.\n"
        "This cannot be undone."
    )
    await query.edit_message_text(text, reply_markup=_confirm_keyboard(trip_id), parse_mode="Markdown")
    return STATE_CONFIRM


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    trip_id = int(query.data.split(":", 1)[1])
    group_chat_id = str(update.effective_chat.id)

    try:
        deleted = await run_in_executor(queries.delete_trip, trip_id, group_chat_id)
    except Exception as exc:
        logger.error("Failed to delete trip %s: %s", trip_id, exc)
        await query.edit_message_text("❌ Failed to delete trip. Please try again.")
        return ConversationHandler.END

    trip = context.user_data.get("tdel_trip", {})
    if deleted:
        count = trip.get("expense_count", 0)
        await query.edit_message_text(
            f"✅ Trip *{trip.get('name', '')}* deleted.\n"
            f"{count} expense{'s' if count != 1 else ''} unlinked.",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text("❌ Trip not found or already deleted.")

    context.user_data.clear()
    return ConversationHandler.END


async def handle_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    return await _show_list(update, context, edit=True)


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


async def handle_unexpected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Please use the buttons above to select a trip.")
    return None  # Stay in current state


def build_tripdelete_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("tripdelete", cmd_tripdelete)],
        states={
            STATE_PICK: [
                CallbackQueryHandler(handle_pick, pattern=r"^tdel_pick:"),
                CallbackQueryHandler(handle_cancel, pattern=r"^tdel_cancel$"),
            ],
            STATE_CONFIRM: [
                CallbackQueryHandler(handle_confirm, pattern=r"^tdel_confirm:"),
                CallbackQueryHandler(handle_back, pattern=r"^tdel_back$"),
                CallbackQueryHandler(handle_cancel, pattern=r"^tdel_cancel$"),
            ],
        },
        fallbacks=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unexpected)],
        per_user=True,
        per_chat=True,
    )
