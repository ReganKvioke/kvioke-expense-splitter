"""Two-step /delete command: list recent expenses → confirm → delete."""
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
from bot.utils.format import fmt_sgd, fmt_amount, fmt_datetime_compact, fmt_datetime, fmt_category

logger = logging.getLogger(__name__)

STATE_PICK, STATE_CONFIRM = range(2)
PAGE_SIZE = 8


def _expense_list_keyboard(expenses: list, page: int, total: int) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            f"{fmt_datetime_compact(e['created_at'])} · {e['description'][:20]} · {fmt_amount(e['amount'], e['currency'])} · {e['paid_by_name']}",
            callback_data=f"del_pick:{e['id']}",
        )]
        for e in expenses
    ]

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"del_page:{page - 1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"del_page:{page + 1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="del_cancel")])
    return InlineKeyboardMarkup(buttons)


def _confirm_keyboard(expense_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑 Yes, delete", callback_data=f"del_confirm:{expense_id}"),
            InlineKeyboardButton("◀ Back", callback_data="del_back"),
        ]
    ])


async def _show_list(update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 0, edit: bool = False) -> int:
    group_chat_id = str(update.effective_chat.id)
    trip_id = context.user_data.get("del_trip_id")

    all_expenses = await run_in_executor(
        queries.get_recent_expenses_for_group, group_chat_id, 100, trip_id
    )

    if not all_expenses:
        text = "No expenses found in this group."
        if edit:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return ConversationHandler.END

    context.user_data["del_all"] = all_expenses
    context.user_data["del_page"] = page

    trip_name = context.user_data.get("del_trip_name", "")
    slice_ = all_expenses[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]
    text = (
        f"🗑 *{trip_name}* — Select an expense to delete "
        f"({page * PAGE_SIZE + 1}–{page * PAGE_SIZE + len(slice_)} of {len(all_expenses)}):"
    )
    keyboard = _expense_list_keyboard(slice_, page, len(all_expenses))

    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

    return STATE_PICK


@require_auth
async def cmd_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_chat_id = str(update.effective_chat.id)
    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)

    context.user_data.clear()
    if active_trip:
        context.user_data["del_trip_id"] = active_trip["id"]
        context.user_data["del_trip_name"] = active_trip["name"]
    else:
        context.user_data["del_trip_id"] = None
        context.user_data["del_trip_name"] = "All expenses"
    return await _show_list(update, context, page=0, edit=False)


async def handle_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":", 1)[1])
    return await _show_list(update, context, page=page, edit=True)


async def handle_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    expense_id = int(query.data.split(":", 1)[1])
    group_chat_id = str(update.effective_chat.id)

    expense = await run_in_executor(queries.get_expense_by_id, expense_id, group_chat_id)

    if not expense:
        await query.edit_message_text("❌ Expense not found.")
        return ConversationHandler.END

    context.user_data["del_expense"] = expense

    text = (
        "⚠️ *Confirm deletion:*\n\n"
        f"Date: {fmt_datetime(expense['created_at'])}\n"
        f"Description: {expense['description']}\n"
        f"Amount: {fmt_amount(expense['amount'], expense['currency'])} ({fmt_sgd(expense['amount_sgd'])})\n"
        f"Category: {fmt_category(expense['category'])}\n"
        f"Paid by: {expense['paid_by_name']}\n"
        f"Split: {expense['split_method']}\n\n"
        "This will also remove all associated splits. This cannot be undone."
    )
    await query.edit_message_text(text, reply_markup=_confirm_keyboard(expense_id), parse_mode="Markdown")
    return STATE_CONFIRM


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    expense_id = int(query.data.split(":", 1)[1])
    group_chat_id = str(update.effective_chat.id)

    try:
        deleted = await run_in_executor(queries.delete_expense, expense_id, group_chat_id)
    except Exception as exc:
        logger.error("Failed to delete expense %s: %s", expense_id, exc)
        await query.edit_message_text("❌ Failed to delete expense. Please try again.")
        return ConversationHandler.END

    expense = context.user_data.get("del_expense", {})
    if deleted:
        await query.edit_message_text(
            f"✅ Deleted: *{expense.get('description', '')}* — {fmt_amount(expense.get('amount', 0), expense.get('currency', 'SGD'))}",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text("❌ Expense not found or already deleted.")

    context.user_data.clear()
    return ConversationHandler.END


async def handle_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    page = context.user_data.get("del_page", 0)
    return await _show_list(update, context, page=page, edit=True)


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


async def handle_unexpected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Please use the buttons above to select an expense.")
    return None  # Stay in current state


def build_delete_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("delete", cmd_delete)],
        states={
            STATE_PICK: [
                CallbackQueryHandler(handle_page, pattern=r"^del_page:"),
                CallbackQueryHandler(handle_pick, pattern=r"^del_pick:"),
                CallbackQueryHandler(handle_cancel, pattern=r"^del_cancel$"),
            ],
            STATE_CONFIRM: [
                CallbackQueryHandler(handle_confirm, pattern=r"^del_confirm:"),
                CallbackQueryHandler(handle_back, pattern=r"^del_back$"),
                CallbackQueryHandler(handle_cancel, pattern=r"^del_cancel$"),
            ],
        },
        fallbacks=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unexpected)],
        per_user=True,
        per_chat=True,
    )
