"""
/exporthtml — Generate a self-contained HTML expense dashboard and send as a file.
"""
import io
import json
import logging

from telegram import Update
from telegram.ext import ContextTypes

from bot.db import queries
from bot.db.database import run_in_executor
from bot.middleware.auth import require_auth
from bot.services.balances import compute_net_balances, simplify_debts
from bot.utils.format import fmt_amount, fmt_datetime_local, tz_abbrev, now_utc_iso

logger = logging.getLogger(__name__)


def _build_payload(group_chat_id: str) -> dict:
    """Fetch all relevant data from the DB and return a JSON-serialisable payload."""
    active_trip = queries.get_active_trip(group_chat_id)

    if active_trip:
        trip_id = active_trip["id"]
        currency = active_trip["default_currency"]
        trip_info = {
            "name": active_trip["name"],
            "currency": currency,
            "started_at": active_trip["started_at"],
            "ended_at": active_trip.get("ended_at"),
            "status": "active",
        }
    else:
        trip_id = None
        currency = "SGD"
        trip_info = {
            "name": "All Expenses",
            "currency": "SGD",
            "started_at": None,
            "ended_at": None,
            "status": "no_trip",
        }

    tz = tz_abbrev(currency)
    expenses_raw = queries.get_expenses_for_group(group_chat_id, trip_id=trip_id)
    settlements_raw = queries.get_settlements_for_trip(group_chat_id, trip_id)
    balance_data = queries.get_balance_data(group_chat_id, trip_id)
    net = compute_net_balances(balance_data)
    transfers = simplify_debts(net)
    names = balance_data["users"]
    categories_raw = queries.get_expenses_by_category(group_chat_id, trip_id)

    expenses = []
    for e in expenses_raw:
        expenses.append({
            "date": fmt_datetime_local(e["created_at"], currency),
            "description": e["description"],
            "category": e["category"],
            "amount_fmt": fmt_amount(e["amount"], e["currency"]),
            "amount_sgd": round(e["amount_sgd"], 2),
            "paid_by": e["paid_by_name"],
            "split": e["split_method"],
            "currency": e["currency"],
        })

    settlements = []
    for s in settlements_raw:
        settlements.append({
            "date": fmt_datetime_local(s["created_at"], currency),
            "from_name": s["from_name"],
            "to_name": s["to_name"],
            "amount_sgd": round(s["amount_sgd"], 2),
        })

    balances = {
        "net": [
            {"name": names.get(uid, str(uid)), "amount": round(v, 2)}
            for uid, v in sorted(net.items(), key=lambda x: x[1])
        ],
        "transfers": [
            {"from": names.get(f, str(f)), "to": names.get(t, str(t)), "amount": a}
            for f, t, a in transfers
        ],
    }

    person_spending: dict[str, float] = {}
    for e in expenses_raw:
        n = e["paid_by_name"]
        person_spending[n] = person_spending.get(n, 0) + e["amount_sgd"]

    total_sgd = sum(e["amount_sgd"] for e in expenses_raw)

    return {
        "trip": trip_info,
        "total_sgd": round(total_sgd, 2),
        "currency": currency,
        "tz": tz,
        "expenses": expenses,
        "settlements": settlements,
        "balances": balances,
        "categories": [
            {"category": c["category"], "total_sgd": round(c["total_sgd"], 2), "count": c["count"]}
            for c in categories_raw
        ],
        "person_spending": [
            {"name": k, "amount": round(v, 2)}
            for k, v in sorted(person_spending.items(), key=lambda x: -x[1])
        ],
        "generated_at": now_utc_iso(),
    }


def _render_html(payload: dict) -> str:
    """Render the self-contained HTML dashboard from the payload dict."""
    json_data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    trip_name = payload["trip"]["name"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{trip_name} — Expense Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f0f2f5;color:#1a1a2e;font-size:14px;line-height:1.5}}
a{{color:inherit;text-decoration:none}}
.container{{max-width:1100px;margin:0 auto;padding:24px 16px}}
h1{{font-size:1.6rem;font-weight:700;margin-bottom:4px}}
h2{{font-size:1.1rem;font-weight:600;margin-bottom:12px;color:#444}}
.badge{{display:inline-block;padding:2px 10px;border-radius:20px;font-size:11px;font-weight:600;letter-spacing:.4px;text-transform:uppercase}}
.badge-active{{background:#d1fae5;color:#065f46}}
.badge-ended{{background:#e5e7eb;color:#374151}}
.badge-nottrip{{background:#fef3c7;color:#92400e}}
.meta{{color:#6b7280;font-size:12px;margin-bottom:24px}}
.cards{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-bottom:24px}}
.card{{background:#fff;border-radius:10px;padding:18px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.card-label{{font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px}}
.card-value{{font-size:1.6rem;font-weight:700;color:#1a1a2e}}
.card-sub{{font-size:11px;color:#9ca3af;margin-top:2px}}
.section{{background:#fff;border-radius:10px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:20px}}
.charts-row{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}}
@media(max-width:640px){{.charts-row{{grid-template-columns:1fr}}}}
.chart-wrap{{background:#fff;border-radius:10px;padding:20px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
.chart-wrap canvas{{max-height:240px}}
.balance-grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}
@media(max-width:640px){{.balance-grid{{grid-template-columns:1fr}}}}
.balance-list{{list-style:none}}
.balance-list li{{display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #f3f4f6}}
.balance-list li:last-child{{border-bottom:none}}
.bal-name{{font-weight:500}}
.bal-amt{{font-weight:600;font-variant-numeric:tabular-nums}}
.bal-pos{{color:#059669}}
.bal-neg{{color:#dc2626}}
.bal-zero{{color:#9ca3af}}
.transfer-list{{list-style:none}}
.transfer-list li{{padding:7px 0;border-bottom:1px solid #f3f4f6;display:flex;gap:8px;align-items:center}}
.transfer-list li:last-child{{border-bottom:none}}
.arrow{{color:#9ca3af}}
.tf-amt{{margin-left:auto;font-weight:600;font-variant-numeric:tabular-nums;color:#2563eb}}
.search-bar{{margin-bottom:12px}}
.search-bar input{{width:100%;padding:8px 12px;border:1px solid #e5e7eb;border-radius:8px;font-size:13px;outline:none}}
.search-bar input:focus{{border-color:#6366f1;box-shadow:0 0 0 2px rgba(99,102,241,.15)}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th{{text-align:left;padding:8px 10px;background:#f9fafb;color:#6b7280;font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:.4px;cursor:pointer;user-select:none;white-space:nowrap}}
th:hover{{background:#f3f4f6;color:#374151}}
th.sorted-asc::after{{content:" ▲"}}
th.sorted-desc::after{{content:" ▼"}}
td{{padding:8px 10px;border-bottom:1px solid #f3f4f6;vertical-align:middle}}
tr:last-child td{{border-bottom:none}}
tr:hover td{{background:#fafafa}}
.tag{{display:inline-block;padding:1px 7px;border-radius:4px;font-size:11px;font-weight:500;background:#ede9fe;color:#5b21b6}}
.empty{{text-align:center;color:#9ca3af;padding:32px 0;font-size:13px}}
.section-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}}
.count-badge{{font-size:11px;font-weight:600;background:#e0e7ff;color:#3730a3;padding:2px 8px;border-radius:10px}}
footer{{text-align:center;color:#9ca3af;font-size:11px;margin-top:16px;padding-bottom:32px}}
</style>
</head>
<body>
<script>const DATA = {json_data};</script>
<div class="container">

<div style="margin-bottom:20px">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">
    <h1 id="trip-name"></h1>
    <span id="trip-badge" class="badge"></span>
  </div>
  <p class="meta" id="meta-line"></p>
</div>

<div class="cards" id="stat-cards"></div>

<div class="section">
  <h2>Balances</h2>
  <div class="balance-grid">
    <div>
      <p style="font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">Net Position (SGD)</p>
      <ul class="balance-list" id="balance-list"></ul>
    </div>
    <div>
      <p style="font-size:11px;font-weight:600;color:#9ca3af;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px">Suggested Transfers</p>
      <ul class="transfer-list" id="transfer-list"></ul>
    </div>
  </div>
</div>

<div class="charts-row">
  <div class="chart-wrap">
    <h2>Spending by Category</h2>
    <canvas id="cat-chart"></canvas>
  </div>
  <div class="chart-wrap">
    <h2>Spending by Person</h2>
    <canvas id="person-chart"></canvas>
  </div>
</div>

<div class="section">
  <div class="section-header">
    <h2 style="margin:0">Expenses</h2>
    <span class="count-badge" id="exp-count"></span>
  </div>
  <div class="search-bar"><input type="text" id="search" placeholder="Search description, category, paid by…"></div>
  <div style="overflow-x:auto">
    <table>
      <thead>
        <tr>
          <th data-col="date">Date</th>
          <th data-col="description">Description</th>
          <th data-col="category">Category</th>
          <th data-col="amount_fmt" style="text-align:right">Amount</th>
          <th data-col="amount_sgd" style="text-align:right">SGD</th>
          <th data-col="paid_by">Paid by</th>
          <th data-col="split">Split</th>
        </tr>
      </thead>
      <tbody id="exp-tbody"></tbody>
    </table>
    <p class="empty" id="exp-empty" style="display:none">No expenses match your search.</p>
  </div>
</div>

<div class="section">
  <div class="section-header">
    <h2 style="margin:0">Settlements</h2>
    <span class="count-badge" id="stl-count"></span>
  </div>
  <div style="overflow-x:auto">
    <table>
      <thead>
        <tr>
          <th>Date</th>
          <th>From</th>
          <th>To</th>
          <th style="text-align:right">Amount (SGD)</th>
        </tr>
      </thead>
      <tbody id="stl-tbody"></tbody>
    </table>
    <p class="empty" id="stl-empty" style="display:none">No settlements recorded.</p>
  </div>
</div>

<footer id="footer"></footer>
</div>

<script>
const PALETTE = ['#6366f1','#f43f5e','#f59e0b','#10b981','#3b82f6','#8b5cf6','#ec4899','#14b8a6','#ef4444','#84cc16'];
const fmt = n => 'SGD ' + n.toFixed(2);

// Header
document.getElementById('trip-name').textContent = DATA.trip.name;
const badge = document.getElementById('trip-badge');
if (DATA.trip.status === 'active') {{
  badge.textContent = 'Active';
  badge.className = 'badge badge-active';
}} else if (DATA.trip.status === 'no_trip') {{
  badge.textContent = 'No Active Trip';
  badge.className = 'badge badge-nottrip';
}} else {{
  badge.textContent = 'Ended';
  badge.className = 'badge badge-ended';
}}

const genDate = new Date(DATA.generated_at).toLocaleString();
document.getElementById('meta-line').textContent =
  `Currency: ${{DATA.currency}} · Timezone: ${{DATA.tz}} · Generated: ${{genDate}} UTC`;

// Stat cards
const nPeople = DATA.balances.net.length;
const cards = [
  {{ label: 'Total Spent', value: fmt(DATA.total_sgd), sub: `${{DATA.currency}} equivalent` }},
  {{ label: 'Expenses', value: DATA.expenses.length, sub: 'transactions' }},
  {{ label: 'Participants', value: nPeople, sub: 'people' }},
  {{ label: 'Settlements', value: DATA.settlements.length, sub: 'payments made' }},
];
document.getElementById('stat-cards').innerHTML = cards.map(c =>
  `<div class="card"><div class="card-label">${{c.label}}</div><div class="card-value">${{c.value}}</div><div class="card-sub">${{c.sub}}</div></div>`
).join('');

// Balances
const balList = document.getElementById('balance-list');
if (DATA.balances.net.length === 0) {{
  balList.innerHTML = '<li style="color:#9ca3af">No data yet.</li>';
}} else {{
  balList.innerHTML = DATA.balances.net.map(b => {{
    const cls = b.amount > 0.005 ? 'bal-pos' : b.amount < -0.005 ? 'bal-neg' : 'bal-zero';
    const sign = b.amount > 0.005 ? '+ ' : '';
    return `<li><span class="bal-name">${{b.name}}</span><span class="bal-amt ${{cls}}">${{sign}}${{fmt(b.amount)}}</span></li>`;
  }}).join('');
}}

const tfList = document.getElementById('transfer-list');
if (DATA.balances.transfers.length === 0) {{
  tfList.innerHTML = '<li style="color:#9ca3af">All settled up! 🎉</li>';
}} else {{
  tfList.innerHTML = DATA.balances.transfers.map(t =>
    `<li><strong>${{t.from}}</strong><span class="arrow">→</span><strong>${{t.to}}</strong><span class="tf-amt">${{fmt(t.amount)}}</span></li>`
  ).join('');
}}

// Category chart
if (DATA.categories.length > 0) {{
  new Chart(document.getElementById('cat-chart'), {{
    type: 'doughnut',
    data: {{
      labels: DATA.categories.map(c => c.category.charAt(0).toUpperCase() + c.category.slice(1)),
      datasets: [{{ data: DATA.categories.map(c => c.total_sgd), backgroundColor: PALETTE, borderWidth: 2, borderColor: '#fff' }}],
    }},
    options: {{
      plugins: {{
        legend: {{ position: 'bottom', labels: {{ font: {{ size: 11 }}, padding: 10, usePointStyle: true }} }},
        tooltip: {{ callbacks: {{ label: ctx => ` ${{fmt(ctx.parsed)}}` }} }},
      }},
      cutout: '60%',
    }},
  }});
}}

// Person chart
if (DATA.person_spending.length > 0) {{
  new Chart(document.getElementById('person-chart'), {{
    type: 'bar',
    data: {{
      labels: DATA.person_spending.map(p => p.name),
      datasets: [{{ label: 'Paid (SGD)', data: DATA.person_spending.map(p => p.amount), backgroundColor: PALETTE, borderRadius: 6, borderSkipped: false }}],
    }},
    options: {{
      indexAxis: 'y',
      plugins: {{
        legend: {{ display: false }},
        tooltip: {{ callbacks: {{ label: ctx => ` ${{fmt(ctx.parsed.x)}}` }} }},
      }},
      scales: {{
        x: {{ grid: {{ color: '#f3f4f6' }}, ticks: {{ callback: v => 'SGD ' + v }} }},
        y: {{ grid: {{ display: false }} }},
      }},
    }},
  }});
}}

// Expense table
let sortCol = 'date';
let sortDir = -1; // -1 = desc, 1 = asc
let searchQ = '';

function renderExpenses() {{
  const q = searchQ.toLowerCase();
  const filtered = DATA.expenses.filter(e =>
    !q || e.description.toLowerCase().includes(q) ||
    e.category.toLowerCase().includes(q) ||
    e.paid_by.toLowerCase().includes(q) ||
    e.amount_fmt.toLowerCase().includes(q)
  );

  filtered.sort((a, b) => {{
    let va = a[sortCol] ?? '', vb = b[sortCol] ?? '';
    if (typeof va === 'number') return (va - vb) * sortDir;
    return String(va).localeCompare(String(vb)) * sortDir;
  }});

  document.getElementById('exp-count').textContent = filtered.length + ' / ' + DATA.expenses.length;
  const tbody = document.getElementById('exp-tbody');
  const empty = document.getElementById('exp-empty');

  if (filtered.length === 0) {{
    tbody.innerHTML = '';
    empty.style.display = '';
  }} else {{
    empty.style.display = 'none';
    tbody.innerHTML = filtered.map(e =>
      `<tr>
        <td style="white-space:nowrap;color:#6b7280">${{e.date}}</td>
        <td>${{e.description}}</td>
        <td><span class="tag">${{e.category}}</span></td>
        <td style="text-align:right;font-variant-numeric:tabular-nums">${{e.amount_fmt}}</td>
        <td style="text-align:right;font-variant-numeric:tabular-nums;font-weight:600">${{fmt(e.amount_sgd)}}</td>
        <td>${{e.paid_by}}</td>
        <td style="color:#9ca3af;font-size:12px">${{e.split}}</td>
      </tr>`
    ).join('');
  }}

  document.querySelectorAll('th[data-col]').forEach(th => {{
    th.className = th.dataset.col === sortCol ? (sortDir === -1 ? 'sorted-desc' : 'sorted-asc') : '';
  }});
}}

document.querySelectorAll('th[data-col]').forEach(th => {{
  th.addEventListener('click', () => {{
    if (sortCol === th.dataset.col) sortDir *= -1;
    else {{ sortCol = th.dataset.col; sortDir = -1; }}
    renderExpenses();
  }});
}});

document.getElementById('search').addEventListener('input', e => {{
  searchQ = e.target.value;
  renderExpenses();
}});

renderExpenses();

// Settlements table
const stlTbody = document.getElementById('stl-tbody');
const stlEmpty = document.getElementById('stl-empty');
document.getElementById('stl-count').textContent = DATA.settlements.length;
if (DATA.settlements.length === 0) {{
  stlEmpty.style.display = '';
}} else {{
  stlTbody.innerHTML = DATA.settlements.map(s =>
    `<tr>
      <td style="white-space:nowrap;color:#6b7280">${{s.date}}</td>
      <td><strong>${{s.from_name}}</strong></td>
      <td><strong>${{s.to_name}}</strong></td>
      <td style="text-align:right;font-weight:600;font-variant-numeric:tabular-nums">${{fmt(s.amount_sgd)}}</td>
    </tr>`
  ).join('');
}}

document.getElementById('footer').textContent =
  `Generated by KviokeExpenseSplitter · ${{DATA.generated_at.slice(0,10)}}`;
</script>
</body>
</html>"""


@require_auth
async def cmd_exporthtml(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    group_chat_id = str(update.effective_chat.id)

    await update.message.reply_text("⏳ Generating dashboard…")

    try:
        payload = await run_in_executor(_build_payload, group_chat_id)
    except Exception as exc:
        logger.error("exporthtml: failed to build payload: %s", exc)
        await update.message.reply_text("❌ Failed to gather data. Please try again.")
        return

    try:
        html = _render_html(payload)
    except Exception as exc:
        logger.error("exporthtml: failed to render HTML: %s", exc)
        await update.message.reply_text("❌ Failed to generate report. Please try again.")
        return

    trip_name = payload["trip"]["name"].replace(" ", "_").replace("/", "-")
    filename = f"{trip_name}_dashboard.html"

    await update.message.reply_document(
        document=io.BytesIO(html.encode("utf-8")),
        filename=filename,
        caption=(
            f"📊 *{payload['trip']['name']}* — Expense Dashboard\n"
            f"{len(payload['expenses'])} expenses · SGD {payload['total_sgd']:.2f} total\n\n"
            "Open the HTML file in any browser."
        ),
        parse_mode="Markdown",
    )
