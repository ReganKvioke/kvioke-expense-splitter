import logging
from telegram import Update
from telegram.ext import ContextTypes

from bot.db import queries
from bot.db.database import run_in_executor
from bot.middleware.auth import require_auth
from bot.services.balances import compute_net_balances, simplify_debts
from bot.utils.format import fmt_sgd, fmt_balance_line

logger = logging.getLogger(__name__)


@require_auth
async def cmd_balances(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    group_chat_id = str(update.effective_chat.id)

    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)
    if not active_trip:
        await update.message.reply_text(
            "⛔ No active trip. Use /tripstart <name> [currency] to begin a trip first."
        )
        return

    try:
        data = await run_in_executor(queries.get_balance_data, group_chat_id, active_trip["id"])
    except Exception as exc:
        logger.error("Failed to fetch balance data: %s", exc)
        await update.message.reply_text("❌ Could not load balance data. Please try again.")
        return

    if not data["users"]:
        await update.message.reply_text(
            f"No expenses recorded yet for *{active_trip['name']}*.", parse_mode="Markdown"
        )
        return

    net = compute_net_balances(data)
    user_names = data["users"]

    # Sort: biggest debtors first, then creditors
    sorted_users = sorted(net.items(), key=lambda x: x[1])

    # Identify the person who owes the most
    biggest_debtor_id = None
    for uid, bal in sorted_users:
        if bal < -0.005:
            biggest_debtor_id = uid
            break

    lines = [f"💰 *{active_trip['name']} — Balances:*\n"]
    for uid, bal in sorted_users:
        name = user_names.get(uid, f"User#{uid}")
        is_worst = (uid == biggest_debtor_id)
        lines.append(fmt_balance_line(name, bal, is_worst))

    transfers = simplify_debts(net)
    if transfers:
        lines.append("\n*Suggested settlements:*")
        for from_id, to_id, amount in transfers:
            from_name = user_names.get(from_id, f"User#{from_id}")
            to_name = user_names.get(to_id, f"User#{to_id}")
            lines.append(f"• {from_name} → {to_name}: {fmt_sgd(amount)}")
    else:
        lines.append("\n✅ Everyone is settled up!")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
