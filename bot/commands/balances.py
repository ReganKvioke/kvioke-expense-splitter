import logging
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from bot.db import queries
from bot.db.database import run_in_executor
from bot.middleware.auth import require_auth
from bot.services.balances import compute_net_balances, simplify_debts
from bot.utils.format import fmt_sgd, fmt_balance_line

logger = logging.getLogger(__name__)


def _settle_keyboard(
    transfers: list,
    sender_db_id: int,
    names: dict,
) -> InlineKeyboardMarkup | None:
    """Return inline buttons for the sender's own debts, or None if they owe nothing."""
    my_transfers = [(f, t, a) for f, t, a in transfers if f == sender_db_id]
    if not my_transfers:
        return None
    buttons = [
        [InlineKeyboardButton(
            f"💳 Settle {fmt_sgd(a)} → {names.get(t, str(t))}",
            callback_data=f"settle_q:{f}:{t}:{a:.2f}",
        )]
        for f, t, a in my_transfers
    ]
    return InlineKeyboardMarkup(buttons)


async def _send_balances(
    reply_fn,
    group_chat_id: str,
    sender_db_id: int,
) -> None:
    """Core balances logic — fetch, format, and send via reply_fn."""
    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)
    if not active_trip:
        await reply_fn("⛔ No active trip. Use /tripstart <name> [currency] to begin a trip first.")
        return

    try:
        data = await run_in_executor(queries.get_balance_data, group_chat_id, active_trip["id"])
    except Exception as exc:
        logger.error("Failed to fetch balance data: %s", exc)
        await reply_fn("❌ Could not load balance data. Please try again.")
        return

    if not data["users"]:
        await reply_fn(
            f"No expenses recorded yet for *{active_trip['name']}*.",
            parse_mode="Markdown",
        )
        return

    net = compute_net_balances(data)
    user_names = data["users"]
    sorted_users = sorted(net.items(), key=lambda x: x[1])

    biggest_debtor_id = None
    for uid, bal in sorted_users:
        if bal < -0.005:
            biggest_debtor_id = uid
            break

    lines = [f"💰 *{active_trip['name']} — Balances:*\n"]
    for uid, bal in sorted_users:
        name = user_names.get(uid, f"User#{uid}")
        lines.append(fmt_balance_line(name, bal, uid == biggest_debtor_id))

    transfers = simplify_debts(net)
    if transfers:
        lines.append("\n*Suggested settlements:*")
        for from_id, to_id, amount in transfers:
            from_name = user_names.get(from_id, f"User#{from_id}")
            to_name = user_names.get(to_id, f"User#{to_id}")
            lines.append(f"• {from_name} → {to_name}: {fmt_sgd(amount)}")
    else:
        lines.append("\n✅ Everyone is settled up!")

    keyboard = _settle_keyboard(transfers, sender_db_id, user_names)
    await reply_fn("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)


@require_auth
async def cmd_balances(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    sender = update.effective_user
    sender_display = sender.username or sender.first_name or str(sender.id)
    sender_db_id = await run_in_executor(queries.upsert_user, str(sender.id), sender_display)
    await _send_balances(
        update.message.reply_text,
        str(update.effective_chat.id),
        sender_db_id,
    )


async def handle_post_add_balances(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback for the 'View balances' button on the post-save keyboard."""
    query = update.callback_query
    await query.answer()
    sender = update.effective_user
    sender_display = sender.username or sender.first_name or str(sender.id)
    sender_db_id = await run_in_executor(queries.upsert_user, str(sender.id), sender_display)
    await _send_balances(
        query.message.reply_text,
        str(update.effective_chat.id),
        sender_db_id,
    )


async def handle_settle_quick(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback for the one-tap settle buttons on the balances message."""
    query = update.callback_query

    parts = query.data.split(":")
    from_id = int(parts[1])
    to_id = int(parts[2])
    amount = float(parts[3])

    # Only the debtor may tap their own settle button
    tapper_tg_id = str(query.from_user.id)
    from_user = await run_in_executor(queries.get_user_by_id, from_id)
    if not from_user or from_user.get("telegram_id") != tapper_tg_id:
        await query.answer("❌ This settlement isn't yours to record.", show_alert=True)
        return

    group_chat_id = str(update.effective_chat.id)
    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)
    if not active_trip:
        await query.answer("❌ No active trip found.", show_alert=True)
        return

    to_user = await run_in_executor(queries.get_user_by_id, to_id)
    to_name = to_user["display_name"] if to_user else str(to_id)
    from_name = from_user["display_name"]

    try:
        await run_in_executor(
            queries.insert_settlement,
            from_id, to_id, round(amount, 2), group_chat_id, active_trip["id"],
        )
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            f"✅ Recorded: {from_name} → {to_name}: {fmt_sgd(amount)}"
        )
    except Exception as exc:
        logger.error("settle_quick failed: %s", exc)
        await query.answer("❌ Could not record settlement. Please try again.", show_alert=True)
