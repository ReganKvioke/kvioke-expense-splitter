"""Multi-step /add command using ConversationHandler."""
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
from bot.services.currency import convert_to_sgd
from bot.services.splitting import (
    equal_split,
    discrete_split,
    parse_custom_split_text,
)
from bot.utils.constants import CATEGORIES, CONVERSATION_TIMEOUT, SUPPORTED_CURRENCIES
from bot.utils.format import fmt_sgd, fmt_amount, fmt_category

logger = logging.getLogger(__name__)

# Conversation states
(
    STATE_AMOUNT,
    STATE_PAYER,
    STATE_GUEST_NAME,
    STATE_CATEGORY,
    STATE_DESCRIPTION,
    STATE_SPLIT_METHOD,
    STATE_CUSTOM_SPLITS,
    STATE_CONFIRM,
) = range(8)

# Context data keys
KEY_AMOUNT = "amount"
KEY_CURRENCY = "currency"
KEY_AMOUNT_SGD = "amount_sgd"
KEY_EXCHANGE_RATE = "exchange_rate"
KEY_PAYER_DB_ID = "payer_db_id"
KEY_PAYER_NAME = "payer_name"
KEY_CATEGORY = "category"
KEY_DESCRIPTION = "description"
KEY_SPLIT_METHOD = "split_method"
KEY_CUSTOM_SPLITS = "custom_splits"  # list of (user_id, amount_sgd)


def _category_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(fmt_category(cat), callback_data=f"cat:{cat}")
        for cat in CATEGORIES
    ]
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


def _payer_keyboard(other_members: list) -> InlineKeyboardMarkup:
    """Inline keyboard with 'Me' + one button per known user + 'New guest' option."""
    buttons = [[InlineKeyboardButton("👤 Me", callback_data="payer:me")]]
    for m in other_members:
        label = f"🧳 {m['display_name']}" if m.get("is_guest") else f"@{m['display_name']}"
        buttons.append([InlineKeyboardButton(label, callback_data=f"payer:{m['id']}")])
    buttons.append([InlineKeyboardButton("➕ New guest payer", callback_data="payer:guest_new")])
    buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="payer:cancel")])
    return InlineKeyboardMarkup(buttons)


def _split_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Equal split", callback_data="split:equal"),
            InlineKeyboardButton("Custom split", callback_data="split:discrete"),
        ]
    ])


def _confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Confirm", callback_data="confirm:yes"),
            InlineKeyboardButton("❌ Cancel", callback_data="confirm:no"),
        ]
    ])


def _build_summary(data: dict, users_by_id: dict | None = None) -> str:
    splits = data.get(KEY_CUSTOM_SPLITS, [])
    method = data[KEY_SPLIT_METHOD]

    lines = [
        "📝 *Expense Summary:*",
        f"Paid by: {data.get(KEY_PAYER_NAME, '?')}",
        f"Amount: {data[KEY_AMOUNT]} {data[KEY_CURRENCY]} ({fmt_sgd(data[KEY_AMOUNT_SGD])})",
        f"Category: {fmt_category(data[KEY_CATEGORY])}",
        f"Description: {data[KEY_DESCRIPTION]}",
        f"Split: {'Custom' if method == 'discrete' else 'Equal'}",
    ]

    if splits and method == "discrete" and users_by_id:
        lines.append("Shares:")
        for uid, amt in splits:
            lines.append(f"  • {users_by_id.get(uid, str(uid))}: {fmt_sgd(amt)}")

    return "\n".join(lines)


@require_auth
async def cmd_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_chat_id = str(update.effective_chat.id)
    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)
    if not active_trip:
        await update.message.reply_text(
            "⛔ No active trip. Use /tripstart <name> [currency] to begin a trip first."
        )
        return ConversationHandler.END

    context.user_data.clear()
    context.user_data["_trip_id"] = active_trip["id"]
    await update.message.reply_text(
        f"💸 Trip: *{active_trip['name']}*\n\n"
        "How much did you spend? (e.g. `50 USD`, `30 SGD`, `5000 JPY`)\n"
        "Currency defaults to SGD if omitted.\n\n"
        "Send /cancel to abort.",
        parse_mode="Markdown",
    )
    return STATE_AMOUNT


async def handle_amount(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()
    parts = text.split()

    try:
        amount = float(parts[0])
    except (ValueError, IndexError):
        await update.message.reply_text("❌ Invalid amount. Try again (e.g. `50`, `50 USD`).")
        return STATE_AMOUNT

    if amount <= 0:
        await update.message.reply_text("❌ Amount must be positive. Try again.")
        return STATE_AMOUNT

    currency = parts[1].upper() if len(parts) > 1 else "SGD"
    if currency not in SUPPORTED_CURRENCIES:
        await update.message.reply_text(
            f"❌ Unsupported currency `{currency}`. Supported: {', '.join(sorted(SUPPORTED_CURRENCIES))}",
            parse_mode="Markdown",
        )
        return STATE_AMOUNT

    # Convert to SGD immediately to validate the API is available
    amount_sgd, exchange_rate = await convert_to_sgd(amount, currency)
    if amount_sgd is None:
        await update.message.reply_text(
            "❌ Could not fetch exchange rates right now. Please try again later."
        )
        return STATE_AMOUNT

    context.user_data[KEY_AMOUNT] = amount
    context.user_data[KEY_CURRENCY] = currency
    context.user_data[KEY_AMOUNT_SGD] = round(amount_sgd, 2)
    context.user_data[KEY_EXCHANGE_RATE] = exchange_rate

    current_tg_id = str(update.effective_user.id)
    all_users = await run_in_executor(queries.get_all_known_users, current_tg_id)

    # Build a lookup map (db_id → user row) for use in handle_payer
    context.user_data["_payer_options"] = {u["id"]: u for u in all_users}

    await update.message.reply_text(
        f"Got it: {amount} {currency} = {fmt_sgd(amount_sgd)}\n\nWho paid?",
        reply_markup=_payer_keyboard(all_users),
    )
    return STATE_PAYER


async def handle_payer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    choice = query.data.split(":", 1)[1]

    if choice == "cancel":
        context.user_data.clear()
        await query.edit_message_text("❌ Expense entry cancelled.")
        return ConversationHandler.END

    if choice == "guest_new":
        await query.edit_message_text(
            "Enter the guest's name (e.g. `John`, `Alice's friend`):\n\nSend /cancel to abort.",
            parse_mode="Markdown",
        )
        return STATE_GUEST_NAME

    if choice == "me":
        user = update.effective_user
        display_name = user.username or user.first_name or str(user.id)
        payer_db_id = await run_in_executor(queries.upsert_user, str(user.id), display_name)
        payer_name = display_name
    else:
        payer_db_id = int(choice)
        payer_options: dict = context.user_data.get("_payer_options", {})
        user_row = payer_options.get(payer_db_id, {})
        payer_name = user_row.get("display_name", f"user#{payer_db_id}") if user_row else f"user#{payer_db_id}"

    context.user_data[KEY_PAYER_DB_ID] = payer_db_id
    context.user_data[KEY_PAYER_NAME] = payer_name

    await query.edit_message_text(
        f"Paid by: *{payer_name}*\n\nSelect a category:",
        reply_markup=_category_keyboard(),
        parse_mode="Markdown",
    )
    return STATE_CATEGORY


async def handle_guest_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    if not name:
        await update.message.reply_text("❌ Name cannot be empty. Try again.")
        return STATE_GUEST_NAME

    payer_db_id = await run_in_executor(queries.create_guest_user, name)
    context.user_data[KEY_PAYER_DB_ID] = payer_db_id
    context.user_data[KEY_PAYER_NAME] = name

    await update.message.reply_text(
        f"Guest added: *{name}*\n\nSelect a category:",
        reply_markup=_category_keyboard(),
        parse_mode="Markdown",
    )
    return STATE_CATEGORY


async def handle_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    category = query.data.split(":", 1)[1]
    context.user_data[KEY_CATEGORY] = category

    await query.edit_message_text(
        f"Category: *{category.capitalize()}*\n\nShort description? (e.g. `dinner at hawker centre`)",
        parse_mode="Markdown",
    )
    return STATE_DESCRIPTION


async def handle_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    description = update.message.text.strip()
    if not description:
        await update.message.reply_text("❌ Description cannot be empty. Try again.")
        return STATE_DESCRIPTION

    context.user_data[KEY_DESCRIPTION] = description

    await update.message.reply_text(
        "How should this be split?",
        reply_markup=_split_keyboard(),
    )
    return STATE_SPLIT_METHOD


async def handle_split_method(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    method = query.data.split(":", 1)[1]
    context.user_data[KEY_SPLIT_METHOD] = method

    group_chat_id = str(update.effective_chat.id)

    if method == "equal":
        payer_db_id = context.user_data[KEY_PAYER_DB_ID]
        payer_name = context.user_data[KEY_PAYER_NAME]

        trip_id = context.user_data.get("_trip_id")
        if trip_id:
            group_users = await run_in_executor(queries.get_trip_participants, trip_id)
            if not group_users:
                group_users = await run_in_executor(queries.get_all_users_in_group, group_chat_id)
        else:
            group_users = await run_in_executor(queries.get_all_users_in_group, group_chat_id)

        # Ensure the payer is always in the split pool
        if not any(u["id"] == payer_db_id for u in group_users):
            group_users.append({"id": payer_db_id, "display_name": payer_name})

        user_ids = [u["id"] for u in group_users]
        splits = equal_split(
            context.user_data[KEY_AMOUNT_SGD], user_ids, payer_db_id
        )
        context.user_data[KEY_CUSTOM_SPLITS] = splits

        summary = _build_summary(context.user_data)
        await query.edit_message_text(
            f"{summary}\n\nConfirm?",
            reply_markup=_confirm_keyboard(),
            parse_mode="Markdown",
        )
        return STATE_CONFIRM

    # Custom split
    trip_id = context.user_data.get("_trip_id")
    if trip_id:
        group_users = await run_in_executor(queries.get_trip_participants, trip_id)
        if not group_users:
            group_users = await run_in_executor(queries.get_all_users_in_group, group_chat_id)
    else:
        group_users = await run_in_executor(queries.get_all_users_in_group, group_chat_id)
    if group_users:
        user_list = ", ".join(f"@{u['display_name']}" for u in group_users)
        hint = f"Known members: {user_list}\n\n"
    else:
        hint = ""

    await query.edit_message_text(
        f"{hint}Enter each person's share:\n"
        "Format: `@name1 amount1, @name2 amount2`\n"
        f"Total must equal {fmt_sgd(context.user_data[KEY_AMOUNT_SGD])}",
        parse_mode="Markdown",
    )
    return STATE_CUSTOM_SPLITS


async def handle_custom_splits(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    group_chat_id = str(update.effective_chat.id)
    trip_id = context.user_data.get("_trip_id")
    if trip_id:
        group_users = await run_in_executor(queries.get_trip_participants, trip_id)
        if not group_users:
            group_users = await run_in_executor(queries.get_all_users_in_group, group_chat_id)
    else:
        group_users = await run_in_executor(queries.get_all_users_in_group, group_chat_id)
    users_by_name = {u["display_name"].lower(): u["id"] for u in group_users}

    splits, errors = parse_custom_split_text(update.message.text, users_by_name)

    if errors:
        await update.message.reply_text(
            "❌ Errors in your input:\n" + "\n".join(f"• {e}" for e in errors) +
            "\n\nPlease try again."
        )
        return STATE_CUSTOM_SPLITS

    if not splits:
        await update.message.reply_text("❌ No valid splits found. Please try again.")
        return STATE_CUSTOM_SPLITS

    total_split = sum(amt for _, amt in splits)
    total_expected = context.user_data[KEY_AMOUNT_SGD]

    if abs(total_split - total_expected) > 0.02:
        await update.message.reply_text(
            f"❌ Split amounts ({fmt_sgd(total_split)}) don't match total ({fmt_sgd(total_expected)}).\n"
            "Please try again."
        )
        return STATE_CUSTOM_SPLITS

    context.user_data[KEY_CUSTOM_SPLITS] = discrete_split(splits)

    users_by_id = {u["id"]: u["display_name"] for u in group_users}
    summary = _build_summary(context.user_data, users_by_id)
    await update.message.reply_text(
        f"{summary}\n\nConfirm?",
        reply_markup=_confirm_keyboard(),
        parse_mode="Markdown",
    )
    return STATE_CONFIRM


async def handle_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    choice = query.data.split(":", 1)[1]

    if choice == "no":
        await query.edit_message_text("❌ Expense cancelled.")
        context.user_data.clear()
        return ConversationHandler.END

    group_chat_id = str(update.effective_chat.id)
    data = context.user_data
    payer_db_id = data[KEY_PAYER_DB_ID]

    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)
    trip_id = active_trip["id"] if active_trip else None

    try:
        expense_id = await run_in_executor(
            queries.insert_expense,
            payer_db_id,
            data[KEY_AMOUNT],
            data[KEY_CURRENCY],
            data[KEY_AMOUNT_SGD],
            data[KEY_EXCHANGE_RATE],
            data[KEY_CATEGORY],
            data[KEY_DESCRIPTION],
            data[KEY_SPLIT_METHOD],
            group_chat_id,
            trip_id,
        )

        splits = data.get(KEY_CUSTOM_SPLITS, [])
        if splits:
            await run_in_executor(queries.insert_expense_splits, expense_id, splits)

        cat_label = fmt_category(data[KEY_CATEGORY])
        trip_note = f" · 📍 {active_trip['name']}" if active_trip else ""
        await query.edit_message_text(
            f"✅ Expense saved!{trip_note}\n({cat_label}) {data[KEY_DESCRIPTION]} -- {fmt_amount(data[KEY_AMOUNT], data[KEY_CURRENCY])}"
        )
    except Exception as exc:
        logger.error("Failed to save expense: %s", exc)
        await query.edit_message_text("❌ Failed to save expense. Please try again.")

    context.user_data.clear()
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    await update.message.reply_text("❌ Expense entry cancelled.")
    return ConversationHandler.END


async def handle_timeout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if update.effective_message:
        await update.effective_message.reply_text(
            "⏱️ Expense entry timed out after 5 minutes. Use /add to start again."
        )
    context.user_data.clear()
    return ConversationHandler.END


def build_add_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            STATE_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_amount)],
            STATE_PAYER: [CallbackQueryHandler(handle_payer, pattern=r"^payer:")],
            STATE_GUEST_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_guest_name)],
            STATE_CATEGORY: [CallbackQueryHandler(handle_category, pattern=r"^cat:")],
            STATE_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_description)],
            STATE_SPLIT_METHOD: [CallbackQueryHandler(handle_split_method, pattern=r"^split:")],
            STATE_CUSTOM_SPLITS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_custom_splits)],
            STATE_CONFIRM: [CallbackQueryHandler(handle_confirm, pattern=r"^confirm:")],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, handle_timeout),
                CallbackQueryHandler(handle_timeout),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        conversation_timeout=CONVERSATION_TIMEOUT,
        per_user=True,
        per_chat=True,
    )
