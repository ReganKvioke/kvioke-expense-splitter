"""Trip management commands: /tripstart (ConversationHandler), /tripend, /tripsummary."""
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
from bot.utils.constants import SUPPORTED_CURRENCIES, CONVERSATION_TIMEOUT
from bot.utils.format import fmt_sgd, fmt_amount, fmt_datetime_local, fmt_category, fmt_date, tz_abbrev

logger = logging.getLogger(__name__)

# Conversation states for /tripstart
(TS_PICK, TS_GUEST_NAME) = range(2)


def _ts_participant_keyboard(all_users: list, selected_ids: set) -> InlineKeyboardMarkup:
    buttons = []
    for u in all_users:
        mark = "✅" if u["id"] in selected_ids else "☐"
        label = (
            f"{mark} 🧳 {u['display_name']}"
            if u.get("is_guest")
            else f"{mark} @{u['display_name']}"
        )
        buttons.append([InlineKeyboardButton(label, callback_data=f"tspart:toggle:{u['id']}")])

    n = len(selected_ids)
    buttons.append([InlineKeyboardButton("➕ Add guest", callback_data="tspart:guest_new")])
    buttons.append([
        InlineKeyboardButton(
            f"✅ Start trip ({n} participant{'s' if n != 1 else ''})",
            callback_data="tspart:confirm",
        )
    ])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="tspart:cancel")])
    return InlineKeyboardMarkup(buttons)


@require_auth
async def cmd_tripstart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_chat_id = str(update.effective_chat.id)

    if not context.args:
        await update.message.reply_text(
            "Usage: /tripstart <name> [currency]\n"
            "Example: /tripstart Japan Trip JPY\n"
            "Currency defaults to SGD if omitted."
        )
        return ConversationHandler.END

    tokens = context.args
    if tokens[-1].upper() in SUPPORTED_CURRENCIES:
        default_currency = tokens[-1].upper()
        name = " ".join(tokens[:-1]).strip()
    else:
        default_currency = "SGD"
        name = " ".join(tokens).strip()

    if not name:
        await update.message.reply_text("❌ Trip name cannot be empty.")
        return ConversationHandler.END

    active = await run_in_executor(queries.get_active_trip, group_chat_id)
    if active:
        await update.message.reply_text(
            f"❌ Trip *{active['name']}* is already active.\n"
            "Use /tripend to close it before starting a new one.",
            parse_mode="Markdown",
        )
        return ConversationHandler.END

    # Upsert the caller so they're always in the users table
    sender = update.effective_user
    sender_display = sender.username or sender.first_name or str(sender.id)
    caller_db_id = await run_in_executor(queries.upsert_user, str(sender.id), sender_display)

    all_users = await run_in_executor(queries.get_all_known_users)
    selected_ids = {caller_db_id}

    context.user_data["_ts_name"] = name
    context.user_data["_ts_currency"] = default_currency
    context.user_data["_ts_all_users"] = all_users
    context.user_data["_ts_selected_ids"] = selected_ids

    await update.message.reply_text(
        f"✈️ *{name}* ({default_currency})\n\nWho's coming on this trip?",
        reply_markup=_ts_participant_keyboard(all_users, selected_ids),
        parse_mode="Markdown",
    )
    return TS_PICK


async def handle_ts_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    parts = query.data.split(":", 2)
    action = parts[1]

    if action == "cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ Trip start cancelled.")
        return ConversationHandler.END

    if action == "guest_new":
        await query.edit_message_text(
            "Enter the guest's name (e.g. `John`, `Alice's friend`):\n\nSend /cancel to abort.",
            parse_mode="Markdown",
        )
        return TS_GUEST_NAME

    if action == "confirm":
        selected_ids = context.user_data.get("_ts_selected_ids", set())
        if not selected_ids:
            await query.answer("⚠️ Select at least one participant.", show_alert=True)
            return TS_PICK

        name = context.user_data["_ts_name"]
        currency = context.user_data["_ts_currency"]
        group_chat_id = str(update.effective_chat.id)

        trip_id = await run_in_executor(queries.create_trip, group_chat_id, name, currency)
        await run_in_executor(queries.add_trip_participants, trip_id, list(selected_ids))

        all_users = context.user_data.get("_ts_all_users", [])
        participants = [u["display_name"] for u in all_users if u["id"] in selected_ids]
        context.user_data.clear()

        await query.edit_message_text(
            f"✈️ Trip *{name}* started!\n"
            f"Default currency: *{currency}*\n"
            f"Participants ({len(participants)}): {', '.join(participants)}\n\n"
            f"/quickadd will now use {currency} by default.\n"
            "Use /tripend when the trip is over.",
            parse_mode="Markdown",
        )
        logger.info(
            "Trip %d '%s' started in group %s with %d participants",
            trip_id, name, group_chat_id, len(participants),
        )
        return ConversationHandler.END

    if action == "toggle":
        user_id = int(parts[2])
        selected_ids = context.user_data.get("_ts_selected_ids", set())
        if user_id in selected_ids:
            selected_ids.discard(user_id)
        else:
            selected_ids.add(user_id)
        context.user_data["_ts_selected_ids"] = selected_ids

        all_users = context.user_data.get("_ts_all_users", [])
        await query.edit_message_reply_markup(
            reply_markup=_ts_participant_keyboard(all_users, selected_ids),
        )
        return TS_PICK

    return TS_PICK


async def handle_ts_guest_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("❌ Name cannot be empty. Try again.")
        return TS_GUEST_NAME

    guest_db_id = await run_in_executor(queries.create_guest_user, name)

    all_users = context.user_data.get("_ts_all_users", [])
    all_users.append({"id": guest_db_id, "display_name": name, "is_guest": 1})
    context.user_data["_ts_all_users"] = all_users

    selected_ids = context.user_data.get("_ts_selected_ids", set())
    selected_ids.add(guest_db_id)
    context.user_data["_ts_selected_ids"] = selected_ids

    trip_name = context.user_data["_ts_name"]
    currency = context.user_data["_ts_currency"]

    await update.message.reply_text(
        f"✅ Guest *{name}* added!\n\n✈️ *{trip_name}* ({currency})\n\nWho's coming on this trip?",
        reply_markup=_ts_participant_keyboard(all_users, selected_ids),
        parse_mode="Markdown",
    )
    return TS_PICK


async def _handle_ts_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    if update.effective_message:
        await update.effective_message.reply_text(
            "⏱️ Trip start timed out. Use /tripstart to try again."
        )
    return ConversationHandler.END


async def cmd_tripstart_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Trip start cancelled.")
    return ConversationHandler.END


def build_tripstart_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("tripstart", cmd_tripstart)],
        states={
            TS_PICK: [CallbackQueryHandler(handle_ts_callback, pattern=r"^tspart:")],
            TS_GUEST_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_ts_guest_name)
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, _handle_ts_timeout),
                CallbackQueryHandler(_handle_ts_timeout),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_tripstart_cancel)],
        conversation_timeout=CONVERSATION_TIMEOUT,
        per_user=True,
        per_chat=True,
    )


@require_auth
async def cmd_tripend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/tripend — Close the currently active trip."""
    group_chat_id = str(update.effective_chat.id)

    active = await run_in_executor(queries.get_active_trip, group_chat_id)
    if not active:
        await update.message.reply_text("No active trip to end.")
        return

    await run_in_executor(queries.end_trip, active["id"])

    expenses = await run_in_executor(queries.get_expenses_for_trip, active["id"])
    total_sgd = sum(e["amount_sgd"] for e in expenses)

    await update.message.reply_text(
        f"🏁 Trip *{active['name']}* ended.\n"
        f"{len(expenses)} expense{'s' if len(expenses) != 1 else ''} · {fmt_sgd(total_sgd)} total\n\n"
        f"Use /tripsummary {active['name']} to review it.",
        parse_mode="Markdown",
    )


@require_auth
async def cmd_tripsummary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    /tripsummary           — list all trips
    /tripsummary <name>    — detailed expense list for that trip
    """
    group_chat_id = str(update.effective_chat.id)

    if not context.args:
        trips = await run_in_executor(queries.get_all_trips, group_chat_id)
        if not trips:
            await update.message.reply_text("No trips recorded for this group yet.")
            return

        lines = ["🗺️ *Trips:*\n"]
        for t in trips:
            status = "🟢 Active" if t["ended_at"] is None else f"🏁 {fmt_date(t['ended_at'])}"
            lines.append(
                f"• *{t['name']}* ({t['default_currency']}) — {status}\n"
                f"  {t['expense_count']} expense{'s' if t['expense_count'] != 1 else ''} · {fmt_sgd(t['total_sgd'])}\n"
                f"  Started {fmt_date(t['started_at'])}"
            )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    name = " ".join(context.args)
    trip = await run_in_executor(queries.get_trip_by_name, group_chat_id, name)
    if not trip:
        await update.message.reply_text(
            f"❌ No trip found with name \"{name}\".\n"
            "Use /tripsummary to see all trips."
        )
        return

    expenses = await run_in_executor(queries.get_expenses_for_trip, trip["id"])

    currency = trip["default_currency"]
    tz = tz_abbrev(currency)
    status = "🟢 Active" if trip["ended_at"] is None else f"🏁 Ended {fmt_date(trip['ended_at'])}"
    total_sgd = sum(e["amount_sgd"] for e in expenses)

    header = (
        f"📋 *{trip['name']}*\n"
        f"{status} · Started {fmt_date(trip['started_at'])}\n"
        f"Default currency: {currency} · {fmt_sgd(total_sgd)} total · {tz}\n"
    )

    if not expenses:
        await update.message.reply_text(header + "\nNo expenses recorded.", parse_mode="Markdown")
        return

    lines = [header]
    for e in expenses:
        lines.append(
            f"• {fmt_datetime_local(e['created_at'], currency)} | {e['description']} | "
            f"{fmt_amount(e['amount'], e['currency'])} | {e['paid_by_name']} | {fmt_category(e['category'])}"
        )

    category_totals: dict[str, float] = {}
    for e in expenses:
        category_totals[e["category"]] = category_totals.get(e["category"], 0) + e["amount_sgd"]

    lines.append("\n*By category (SGD):*")
    for cat, total in sorted(category_totals.items(), key=lambda x: -x[1]):
        lines.append(f"  {fmt_category(cat)}: {fmt_sgd(total)}")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
