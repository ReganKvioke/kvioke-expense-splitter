"""Admin /guestdelete command: list and delete guest users."""
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

logger = logging.getLogger(__name__)

STATE_PICK, STATE_CONFIRM = range(2)


def _guest_list_keyboard(guests: list) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"🧳 {g['display_name']}", callback_data=f"gdel_pick:{g['id']}")]
        for g in guests
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="gdel_cancel")])
    return InlineKeyboardMarkup(buttons)


def _confirm_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🗑 Yes, delete", callback_data=f"gdel_confirm:{user_id}"),
            InlineKeyboardButton("◀ Back", callback_data="gdel_back"),
        ]
    ])


async def _show_list(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False) -> int:
    guests = await run_in_executor(queries.get_all_guest_users)

    if not guests:
        text = "No guest users found."
        if edit:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return ConversationHandler.END

    text = f"🧳 *Guest users* ({len(guests)}) — Select one to delete:"
    keyboard = _guest_list_keyboard(guests)

    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")

    return STATE_PICK


@require_auth
async def cmd_guestdelete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if str(update.effective_user.id) not in get_admin_ids():
        await update.message.reply_text("⛔ This command is for admins only.")
        return ConversationHandler.END

    context.user_data.clear()
    return await _show_list(update, context, edit=False)


async def handle_pick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split(":", 1)[1])

    guest = await run_in_executor(queries.get_user_by_id, user_id)
    if not guest or not guest["is_guest"]:
        await query.edit_message_text("❌ Guest not found.")
        return ConversationHandler.END

    linked = await run_in_executor(queries.get_guest_linked_count, user_id)

    if linked["expenses_paid"] > 0 or linked["splits"] > 0:
        parts = []
        if linked["expenses_paid"]:
            parts.append(f"{linked['expenses_paid']} paid expense(s)")
        if linked["splits"]:
            parts.append(f"{linked['splits']} split(s)")
        await query.edit_message_text(
            f"❌ Cannot delete *{guest['display_name']}* — they are linked to {', '.join(parts)}.\n\n"
            "Delete those records first, then remove the guest.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    context.user_data["gdel_id"] = user_id
    context.user_data["gdel_name"] = guest["display_name"]

    warning_lines = [f"⚠️ Delete guest *{guest['display_name']}*?\n"]
    if linked["settlements"] > 0:
        warning_lines.append(f"⚠️ This will also delete {linked['settlements']} settlement record(s) involving this guest.")
    warning_lines.append("\nThey will be removed from all trip participant lists. This cannot be undone.")

    await query.edit_message_text(
        "\n".join(warning_lines),
        reply_markup=_confirm_keyboard(user_id),
        parse_mode="Markdown",
    )
    return STATE_CONFIRM


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    user_id = int(query.data.split(":", 1)[1])
    name = context.user_data.get("gdel_name", "guest")

    try:
        deleted = await run_in_executor(queries.delete_guest_user, user_id)
    except Exception as exc:
        logger.error("Failed to delete guest user %s: %s", user_id, exc)
        await query.edit_message_text("❌ Failed to delete guest. Please try again.")
        context.user_data.clear()
        return ConversationHandler.END

    if deleted:
        await query.edit_message_text(f"✅ Guest *{name}* deleted.", parse_mode="Markdown")
    else:
        await query.edit_message_text("❌ Guest not found or already deleted.")

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
    await update.message.reply_text("Please use the buttons above to select a guest.")
    return None


def build_guestdelete_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("guestdelete", cmd_guestdelete)],
        states={
            STATE_PICK: [
                CallbackQueryHandler(handle_pick, pattern=r"^gdel_pick:"),
                CallbackQueryHandler(handle_cancel, pattern=r"^gdel_cancel$"),
            ],
            STATE_CONFIRM: [
                CallbackQueryHandler(handle_confirm, pattern=r"^gdel_confirm:"),
                CallbackQueryHandler(handle_back, pattern=r"^gdel_back$"),
                CallbackQueryHandler(handle_cancel, pattern=r"^gdel_cancel$"),
            ],
        },
        fallbacks=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unexpected)],
        per_user=True,
        per_chat=True,
    )
