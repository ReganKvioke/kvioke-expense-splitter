"""Admin /guestmerge — replace a guest user with a real authenticated user."""
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

STATE_PICK_GUEST, STATE_PICK_REAL, STATE_CONFIRM = range(3)


def _guest_list_keyboard(guests: list) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(f"🧳 {g['display_name']}", callback_data=f"gm_guest:{g['id']}")]
        for g in guests
    ]
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="gm_cancel")])
    return InlineKeyboardMarkup(buttons)


def _real_user_keyboard(users: list) -> InlineKeyboardMarkup:
    buttons = []
    for u in users:
        label = f"@{u['display_name']}" if not u.get("is_guest") else f"🧳 {u['display_name']}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"gm_real:{u['id']}")])
    buttons.append([InlineKeyboardButton("◀ Back", callback_data="gm_back_guest")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="gm_cancel")])
    return InlineKeyboardMarkup(buttons)


def _confirm_keyboard(guest_id: int, real_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Merge", callback_data=f"gm_confirm:{guest_id}:{real_id}"),
            InlineKeyboardButton("◀ Back", callback_data="gm_back_real"),
        ],
        [InlineKeyboardButton("❌ Cancel", callback_data="gm_cancel")],
    ])


async def _show_guest_list(update: Update, context: ContextTypes.DEFAULT_TYPE, edit: bool = False) -> int:
    guests = await run_in_executor(queries.get_all_guest_users)
    if not guests:
        text = "No guest users found."
        if edit:
            await update.callback_query.edit_message_text(text)
        else:
            await update.message.reply_text(text)
        return ConversationHandler.END

    text = f"🧳 *Guest users* ({len(guests)}) — Select the guest to replace:"
    keyboard = _guest_list_keyboard(guests)
    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=keyboard, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode="Markdown")
    return STATE_PICK_GUEST


@require_auth
async def cmd_guestmerge(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if str(update.effective_user.id) not in get_admin_ids():
        await update.message.reply_text("⛔ This command is for admins only.")
        return ConversationHandler.END

    context.user_data.clear()
    return await _show_guest_list(update, context, edit=False)


async def handle_pick_guest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    guest_id = int(query.data.split(":", 1)[1])
    guest = await run_in_executor(queries.get_user_by_id, guest_id)
    if not guest or not guest["is_guest"]:
        await query.edit_message_text("❌ Guest not found.")
        return ConversationHandler.END

    context.user_data["gm_guest_id"] = guest_id
    context.user_data["gm_guest_name"] = guest["display_name"]

    # Show only non-guest users as replacement candidates
    all_users = await run_in_executor(queries.get_all_known_users)
    real_users = [u for u in all_users if not u.get("is_guest") and u["id"] != guest_id]

    if not real_users:
        await query.edit_message_text("❌ No real users found to merge into.")
        return ConversationHandler.END

    await query.edit_message_text(
        f"Selected guest: *{guest['display_name']}*\n\nReplace with which real user?",
        reply_markup=_real_user_keyboard(real_users),
        parse_mode="Markdown",
    )
    return STATE_PICK_REAL


async def handle_pick_real(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    real_id = int(query.data.split(":", 1)[1])
    real_user = await run_in_executor(queries.get_user_by_id, real_id)
    if not real_user:
        await query.edit_message_text("❌ User not found.")
        return ConversationHandler.END

    context.user_data["gm_real_id"] = real_id
    context.user_data["gm_real_name"] = real_user["display_name"]

    guest_name = context.user_data["gm_guest_name"]
    real_name = real_user["display_name"]
    guest_id = context.user_data["gm_guest_id"]

    linked = await run_in_executor(queries.get_guest_linked_count, guest_id)
    parts = []
    if linked["expenses_paid"]:
        parts.append(f"{linked['expenses_paid']} expense(s) paid")
    if linked["splits"]:
        parts.append(f"{linked['splits']} split(s)")
    if linked["settlements"]:
        parts.append(f"{linked['settlements']} settlement(s)")
    transfer_line = f"Transfers: {', '.join(parts)}" if parts else "No expenses linked."

    await query.edit_message_text(
        f"*Confirm merge:*\n\n"
        f"🧳 Guest *{guest_name}* → @{real_name}\n\n"
        f"{transfer_line}\n\n"
        f"The guest account will be deleted. This cannot be undone.",
        reply_markup=_confirm_keyboard(guest_id, real_id),
        parse_mode="Markdown",
    )
    return STATE_CONFIRM


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    _, guest_id_str, real_id_str = query.data.split(":")
    guest_id = int(guest_id_str)
    real_id = int(real_id_str)

    guest_name = context.user_data.get("gm_guest_name", "guest")
    real_name = context.user_data.get("gm_real_name", "user")

    try:
        result = await run_in_executor(queries.merge_guest_user, guest_id, real_id)
    except Exception as exc:
        logger.error("Failed to merge guest %s into user %s: %s", guest_id, real_id, exc)
        await query.edit_message_text("❌ Merge failed. Please try again.")
        context.user_data.clear()
        return ConversationHandler.END

    context.user_data.clear()
    await query.edit_message_text(
        f"✅ *{guest_name}* merged into @{real_name}.\n"
        f"Transferred: {result['expenses']} expense(s), "
        f"{result['splits']} split(s), "
        f"{result['settlements']} settlement(s).",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def handle_back_to_guest(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data.pop("gm_guest_id", None)
    context.user_data.pop("gm_guest_name", None)
    return await _show_guest_list(update, context, edit=True)


async def handle_back_to_real(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    guest_id = context.user_data.get("gm_guest_id")
    guest_name = context.user_data.get("gm_guest_name", "")

    all_users = await run_in_executor(queries.get_all_known_users)
    real_users = [u for u in all_users if not u.get("is_guest") and u["id"] != guest_id]

    await query.edit_message_text(
        f"Selected guest: *{guest_name}*\n\nReplace with which real user?",
        reply_markup=_real_user_keyboard(real_users),
        parse_mode="Markdown",
    )
    return STATE_PICK_REAL


async def handle_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("Cancelled.")
    context.user_data.clear()
    return ConversationHandler.END


async def handle_unexpected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Please use the buttons above.")
    return None


def build_guestmerge_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("guestmerge", cmd_guestmerge)],
        states={
            STATE_PICK_GUEST: [
                CallbackQueryHandler(handle_pick_guest, pattern=r"^gm_guest:"),
                CallbackQueryHandler(handle_cancel, pattern=r"^gm_cancel$"),
            ],
            STATE_PICK_REAL: [
                CallbackQueryHandler(handle_pick_real, pattern=r"^gm_real:"),
                CallbackQueryHandler(handle_back_to_guest, pattern=r"^gm_back_guest$"),
                CallbackQueryHandler(handle_cancel, pattern=r"^gm_cancel$"),
            ],
            STATE_CONFIRM: [
                CallbackQueryHandler(handle_confirm, pattern=r"^gm_confirm:"),
                CallbackQueryHandler(handle_back_to_real, pattern=r"^gm_back_real$"),
                CallbackQueryHandler(handle_cancel, pattern=r"^gm_cancel$"),
            ],
        },
        fallbacks=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_unexpected)],
        per_user=True,
        per_chat=True,
    )
