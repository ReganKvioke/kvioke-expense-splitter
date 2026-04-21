"""Multi-step /edit command — change description or category of an existing expense."""
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
from bot.utils.constants import CATEGORIES
from bot.utils.format import fmt_amount, fmt_category, fmt_datetime_local, fmt_sgd

logger = logging.getLogger(__name__)

ED_PICK_EXPENSE, ED_PICK_FIELD, ED_ENTER_DESCRIPTION, ED_PICK_CATEGORY = range(4)
PAGE_SIZE = 8


# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def _expense_list_keyboard(expenses: list, page: int, total: int, currency: str = "SGD") -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(
            f"{fmt_datetime_local(e['created_at'], currency)} · {e['description'][:20]} · "
            f"{fmt_amount(e['amount'], e['currency'])} · {e['paid_by_name']}",
            callback_data=f"edit_pick:{e['id']}",
        )]
        for e in expenses
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"edit_page:{page - 1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"edit_page:{page + 1}"))
    if nav:
        buttons.append(nav)
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel")])
    return InlineKeyboardMarkup(buttons)


def _field_keyboard(expense_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📝 Description", callback_data=f"edit_field:desc:{expense_id}"),
            InlineKeyboardButton("🏷️ Category", callback_data=f"edit_field:cat:{expense_id}"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel")],
    ])


def _category_keyboard(expense_id: int) -> InlineKeyboardMarkup:
    rows = [CATEGORIES[i:i + 2] for i in range(0, len(CATEGORIES), 2)]
    buttons = [
        [
            InlineKeyboardButton(cat.capitalize(), callback_data=f"edit_cat:{cat}:{expense_id}")
            for cat in row
        ]
        for row in rows
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="edit_cancel")])
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------------
# List helper (shared for entry and pagination)
# ---------------------------------------------------------------------------

async def _show_list(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    page: int = 0,
    edit: bool = False,
) -> int:
    group_chat_id = str(update.effective_chat.id)
    trip_id = context.user_data.get("ed_trip_id")

    all_expenses = await run_in_executor(
        queries.get_recent_expenses_for_group, group_chat_id, 100, trip_id
    )

    if not all_expenses:
        msg = "No expenses found."
        if edit:
            await update.callback_query.edit_message_text(msg)
        else:
            await update.message.reply_text(msg)
        return ConversationHandler.END

    context.user_data["ed_all"] = all_expenses
    context.user_data["ed_page"] = page

    trip_name = context.user_data.get("ed_trip_name", "")
    currency = context.user_data.get("ed_currency", "SGD")
    slice_ = all_expenses[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]
    text = (
        f"✏️ *{trip_name}* — Select an expense to edit "
        f"({page * PAGE_SIZE + 1}–{page * PAGE_SIZE + len(slice_)} of {len(all_expenses)}):"
    )
    keyboard = _expense_list_keyboard(slice_, page, len(all_expenses), currency)

    if edit:
        await update.callback_query.edit_message_text(
            text, reply_markup=keyboard, parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

    return ED_PICK_EXPENSE


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

@require_auth
async def cmd_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_chat_id = str(update.effective_chat.id)
    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)

    context.user_data.clear()
    context.user_data["ed_group_chat_id"] = group_chat_id
    if active_trip:
        context.user_data["ed_trip_id"] = active_trip["id"]
        context.user_data["ed_trip_name"] = active_trip["name"]
        context.user_data["ed_currency"] = active_trip["default_currency"]
    else:
        context.user_data["ed_trip_id"] = None
        context.user_data["ed_trip_name"] = "All expenses"
        context.user_data["ed_currency"] = "SGD"

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
    group_chat_id = context.user_data.get("ed_group_chat_id", str(update.effective_chat.id))

    expense = await run_in_executor(queries.get_expense_by_id, expense_id, group_chat_id)
    if not expense:
        await query.edit_message_text("❌ Expense not found.")
        return ConversationHandler.END

    context.user_data["ed_expense"] = expense

    text = (
        f"✏️ Editing:\n\n"
        f"📝 *{expense['description']}*\n"
        f"💰 {fmt_amount(expense['amount'], expense['currency'])} ({fmt_sgd(expense['amount_sgd'])})\n"
        f"🏷️ {fmt_category(expense['category'])}\n\n"
        "What do you want to change?"
    )
    await query.edit_message_text(
        text, reply_markup=_field_keyboard(expense_id), parse_mode="Markdown"
    )
    return ED_PICK_FIELD


async def handle_field(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # callback_data format: edit_field:{desc|cat}:{expense_id}
    parts = query.data.split(":")
    field_type = parts[1]
    expense_id = int(parts[2])

    context.user_data["ed_expense_id"] = expense_id

    if field_type == "desc":
        expense = context.user_data.get("ed_expense", {})
        await query.edit_message_text(
            f"Current description: _{expense.get('description', '')}_\n\nEnter new description:",
            parse_mode="Markdown",
        )
        return ED_ENTER_DESCRIPTION

    # category
    await query.edit_message_text(
        "Select a new category:",
        reply_markup=_category_keyboard(expense_id),
    )
    return ED_PICK_CATEGORY


async def handle_enter_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    new_desc = update.message.text.strip()
    if not new_desc:
        await update.message.reply_text("❌ Description cannot be empty. Try again:")
        return ED_ENTER_DESCRIPTION

    expense_id = context.user_data.get("ed_expense_id")
    group_chat_id = context.user_data.get("ed_group_chat_id", str(update.effective_chat.id))

    try:
        updated = await run_in_executor(
            queries.update_expense_field, expense_id, group_chat_id, "description", new_desc
        )
    except Exception as exc:
        logger.error("Failed to update description for expense %s: %s", expense_id, exc)
        await update.message.reply_text("❌ Failed to update. Please try again.")
        return ConversationHandler.END

    if updated:
        await update.message.reply_text(f"✅ Description updated to: *{new_desc}*", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ Expense not found.")

    context.user_data.clear()
    return ConversationHandler.END


async def handle_pick_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    # callback_data format: edit_cat:{category}:{expense_id}
    parts = query.data.split(":")
    new_cat = parts[1]
    expense_id = int(parts[2])
    group_chat_id = context.user_data.get("ed_group_chat_id", str(update.effective_chat.id))

    if new_cat not in CATEGORIES:
        await query.edit_message_text("❌ Invalid category.")
        return ConversationHandler.END

    try:
        updated = await run_in_executor(
            queries.update_expense_field, expense_id, group_chat_id, "category", new_cat
        )
    except Exception as exc:
        logger.error("Failed to update category for expense %s: %s", expense_id, exc)
        await query.edit_message_text("❌ Failed to update. Please try again.")
        return ConversationHandler.END

    if updated:
        await query.edit_message_text(
            f"✅ Category updated to: {fmt_category(new_cat)}", parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("❌ Expense not found.")

    context.user_data.clear()
    return ConversationHandler.END


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


async def handle_unexpected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Please use the buttons above to select an expense.")
    return None


# ---------------------------------------------------------------------------
# Handler builder
# ---------------------------------------------------------------------------

def build_edit_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("edit", cmd_edit)],
        states={
            ED_PICK_EXPENSE: [
                CallbackQueryHandler(handle_page, pattern=r"^edit_page:"),
                CallbackQueryHandler(handle_pick, pattern=r"^edit_pick:"),
                CallbackQueryHandler(handle_cancel, pattern=r"^edit_cancel$"),
            ],
            ED_PICK_FIELD: [
                CallbackQueryHandler(handle_field, pattern=r"^edit_field:"),
                CallbackQueryHandler(handle_cancel, pattern=r"^edit_cancel$"),
            ],
            ED_ENTER_DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_enter_description),
            ],
            ED_PICK_CATEGORY: [
                CallbackQueryHandler(handle_pick_category, pattern=r"^edit_cat:"),
                CallbackQueryHandler(handle_cancel, pattern=r"^edit_cancel$"),
            ],
        },
        fallbacks=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unexpected),
        ],
        per_user=True,
        per_chat=True,
    )
