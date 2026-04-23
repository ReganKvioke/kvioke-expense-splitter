"""Multi-select /delete command: list expenses → toggle selections → confirm → bulk delete."""
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
from bot.utils.format import fmt_sgd, fmt_amount, fmt_datetime_local, fmt_datetime_full_local, fmt_category

logger = logging.getLogger(__name__)

STATE_PICK, STATE_CONFIRM = range(2)
PAGE_SIZE = 8


def _expense_list_keyboard(
    expenses: list, page: int, total: int, selected: set, currency: str = "SGD"
) -> InlineKeyboardMarkup:
    buttons = []
    for e in expenses:
        check = "✅" if e["id"] in selected else "☐"
        label = (
            f"{check} {fmt_datetime_local(e['created_at'], currency)} · "
            f"{e['description'][:20]} · {fmt_amount(e['amount'], e['currency'])} · {e['paid_by_name']}"
        )
        buttons.append([InlineKeyboardButton(label, callback_data=f"del_toggle:{e['id']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀ Prev", callback_data=f"del_page:{page - 1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton("Next ▶", callback_data=f"del_page:{page + 1}"))
    if nav:
        buttons.append(nav)

    action_row = []
    if selected:
        action_row.append(
            InlineKeyboardButton(f"🗑 Delete ({len(selected)})", callback_data="del_delete_selected")
        )
    action_row.append(InlineKeyboardButton("❌ Cancel", callback_data="del_cancel"))
    buttons.append(action_row)

    return InlineKeyboardMarkup(buttons)


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑 Yes, delete all", callback_data="del_confirm"),
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

    selected: set = context.user_data.get("del_selected", set())
    trip_name = context.user_data.get("del_trip_name", "")
    currency = context.user_data.get("del_currency", "SGD")
    slice_ = all_expenses[page * PAGE_SIZE: (page + 1) * PAGE_SIZE]

    sel_info = f" · {len(selected)} selected" if selected else ""
    text = (
        f"🗑 *{trip_name}* — Tap to select/deselect{sel_info} "
        f"({page * PAGE_SIZE + 1}–{page * PAGE_SIZE + len(slice_)} of {len(all_expenses)}):"
    )
    keyboard = _expense_list_keyboard(slice_, page, len(all_expenses), selected, currency)

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
        context.user_data["del_currency"] = active_trip["default_currency"]
    else:
        context.user_data["del_trip_id"] = None
        context.user_data["del_trip_name"] = "All expenses"
        context.user_data["del_currency"] = "SGD"
    context.user_data["del_selected"] = set()
    return await _show_list(update, context, page=0, edit=False)


async def handle_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    page = int(query.data.split(":", 1)[1])
    return await _show_list(update, context, page=page, edit=True)


async def handle_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query

    expense_id = int(query.data.split(":", 1)[1])
    selected: set = context.user_data.get("del_selected", set())

    if expense_id in selected:
        selected.discard(expense_id)
        await query.answer("Deselected")
    else:
        selected.add(expense_id)
        await query.answer("Selected")

    context.user_data["del_selected"] = selected
    page = context.user_data.get("del_page", 0)
    return await _show_list(update, context, page=page, edit=True)


async def handle_delete_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    selected: set = context.user_data.get("del_selected", set())
    if not selected:
        await query.answer("No expenses selected.", show_alert=True)
        return STATE_PICK

    all_expenses = context.user_data.get("del_all", [])
    expense_map = {e["id"]: e for e in all_expenses}
    currency = context.user_data.get("del_currency", "SGD")

    lines = []
    for eid in sorted(selected):
        e = expense_map.get(eid)
        if e:
            lines.append(
                f"• {fmt_datetime_full_local(e['created_at'], currency)} — "
                f"{e['description']} — {fmt_amount(e['amount'], e['currency'])} ({e['paid_by_name']})"
            )

    text = (
        f"⚠️ *Confirm deletion of {len(selected)} expense(s):*\n\n"
        + "\n".join(lines)
        + "\n\nThis will also remove all associated splits. This cannot be undone."
    )
    await query.edit_message_text(text, reply_markup=_confirm_keyboard(), parse_mode="Markdown")
    return STATE_CONFIRM


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    selected: set = context.user_data.get("del_selected", set())
    group_chat_id = str(update.effective_chat.id)

    deleted_count = 0
    failed_count = 0
    for expense_id in selected:
        try:
            deleted = await run_in_executor(queries.delete_expense, expense_id, group_chat_id)
            if deleted:
                deleted_count += 1
            else:
                failed_count += 1
        except Exception as exc:
            logger.error("Failed to delete expense %s: %s", expense_id, exc)
            failed_count += 1

    if failed_count:
        await query.edit_message_text(
            f"⚠️ Deleted {deleted_count} expense(s). {failed_count} could not be deleted."
        )
    else:
        await query.edit_message_text(f"✅ Deleted {deleted_count} expense(s).")

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
    await update.message.reply_text("Please use the buttons above to select expenses.")
    return None  # Stay in current state


def build_delete_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("delete", cmd_delete)],
        states={
            STATE_PICK: [
                CallbackQueryHandler(handle_page, pattern=r"^del_page:"),
                CallbackQueryHandler(handle_toggle, pattern=r"^del_toggle:"),
                CallbackQueryHandler(handle_delete_selected, pattern=r"^del_delete_selected$"),
                CallbackQueryHandler(handle_cancel, pattern=r"^del_cancel$"),
            ],
            STATE_CONFIRM: [
                CallbackQueryHandler(handle_confirm, pattern=r"^del_confirm$"),
                CallbackQueryHandler(handle_back, pattern=r"^del_back$"),
                CallbackQueryHandler(handle_cancel, pattern=r"^del_cancel$"),
            ],
        },
        fallbacks=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unexpected)],
        per_user=True,
        per_chat=True,
    )
