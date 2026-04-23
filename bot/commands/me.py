import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.db import queries
from bot.db.database import run_in_executor
from bot.middleware.auth import require_auth
from bot.utils.format import fmt_sgd, fmt_balance_line, fmt_category

logger = logging.getLogger(__name__)


@require_auth
async def cmd_me(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/me — Personal stats for the active trip."""
    group_chat_id = str(update.effective_chat.id)

    active_trip = await run_in_executor(queries.get_active_trip, group_chat_id)
    if not active_trip:
        await update.message.reply_text(
            "⛔ No active trip. Use /tripstart <name> [currency] to begin a trip first."
        )
        return

    sender = update.effective_user
    display_name = sender.username or sender.first_name or str(sender.id)
    user_db_id = await run_in_executor(queries.upsert_user, str(sender.id), display_name)

    try:
        stats = await run_in_executor(
            queries.get_personal_stats, group_chat_id, user_db_id, active_trip["id"]
        )
    except Exception as exc:
        logger.error("Personal stats error: %s", exc)
        await update.message.reply_text("❌ Could not load your stats. Please try again.")
        return

    trip_name = active_trip["name"]
    net = stats["net"]
    lines = [f"👤 *Your stats for {trip_name}:*\n"]

    # Net balance
    lines.append(fmt_balance_line(display_name, net))

    # Paid vs owed
    lines.append(f"\n📤 *Paid:* {fmt_sgd(stats['total_paid'])} ({stats['expenses_count']} expense{'s' if stats['expenses_count'] != 1 else ''})")
    lines.append(f"📥 *Your share:* {fmt_sgd(stats['total_owed'])}")

    # Settlements
    if stats["total_sent"] > 0.005 or stats["total_received"] > 0.005:
        lines.append(f"\n💸 *Settlements:*")
        if stats["total_sent"] > 0.005:
            lines.append(f"  Sent: {fmt_sgd(stats['total_sent'])}")
        if stats["total_received"] > 0.005:
            lines.append(f"  Received: {fmt_sgd(stats['total_received'])}")

    # Category breakdown
    if stats["by_category"]:
        lines.append(f"\n🏷️ *Your spending by category:*")
        for row in stats["by_category"]:
            lines.append(f"  {fmt_category(row['category'])}: {fmt_sgd(row['total'])}")

    # Biggest expense paid
    if stats["biggest_expense"]:
        b = stats["biggest_expense"]
        lines.append(
            f"\n🏆 *Biggest expense paid:* {b['description']} ({fmt_sgd(b['amount_sgd'])})"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
