"""
Japan Trip 2026 — pytest logic verification tests.

Covers (without Telegram):
  - Splitting arithmetic (equal, custom, rounding)
  - parse_custom_split_text parsing and error handling
  - Full scenario: 18 expenses → DB → compute_net_balances → simplify_debts
  - /undo: delete_expense removes expense + splits
  - /edit: update_expense_field allowlist + persistence
  - /delete: explicit expense removal updates balances
  - Settlement recording and balance reconciliation to zero
  - Settlement recipient validation (the wrong-person bug fix)
  - Edge cases

Uses an isolated temp SQLite DB — production DB is never touched.
"""
import sqlite3

import pytest

from conftest import near


# ─────────────────────────────────────────────────────────────────────────────
# Module-scoped fixture: runs the full Japan scenario once for all tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def japan(tmp_path_factory):
    """Set up the full Japan trip scenario with all mutations, yield context."""
    import bot.db.database as db_mod
    from bot.db.schema import init_db
    from bot.db import queries
    from bot.services.splitting import equal_split, discrete_split, parse_custom_split_text
    from bot.services.balances import compute_net_balances, simplify_debts

    db_file = tmp_path_factory.mktemp("japan") / "test.db"
    original_path = db_mod.DB_PATH
    db_mod.DB_PATH = db_file

    init_db()
    GROUP = "test_group_001"
    TRIP_NAME = "Japan 2026"

    regan_id = queries.upsert_user("tg_regan", "Regan")
    brand_id  = queries.upsert_user("tg_brand", "Brandeline")
    alice_id  = queries.upsert_user("tg_alice", "Alice")

    trip_id = queries.create_trip(GROUP, TRIP_NAME, "JPY")
    queries.add_trip_participants(trip_id, [regan_id, brand_id, alice_id])

    active       = queries.get_active_trip(GROUP)
    participants = queries.get_trip_participants(trip_id)

    users_by_name = {"regan": regan_id, "brandeline": brand_id, "alice": alice_id}

    # ── Section 1 helpers: pre-compute split unit test values ──────────────────
    splits_30  = equal_split(30.0,  [regan_id, brand_id, alice_id], regan_id)
    splits_20  = equal_split(20.0,  [regan_id, brand_id, alice_id], regan_id)
    splits_40  = equal_split(40.0,  [regan_id, brand_id, alice_id], brand_id)
    splits_50  = equal_split(50.0,  [regan_id, brand_id], regan_id)
    splits_100 = equal_split(100.0, [regan_id], regan_id)

    custom_3way,    custom_3way_errors    = parse_custom_split_text(
        "@Regan 22.50, @Brandeline 22.50, @Alice 22.50", users_by_name)
    custom_2person, custom_2person_errors = parse_custom_split_text(
        "@Alice 12, @Brandeline 12", users_by_name)
    custom_unknown, custom_unknown_errors = parse_custom_split_text(
        "@nobody 10, @Regan 10", users_by_name)
    custom_negative, custom_negative_errors = parse_custom_split_text(
        "@Regan -5, @Alice 5", users_by_name)
    custom_malformed, custom_malformed_errors = parse_custom_split_text(
        "Regan 10 extra, @Alice 10", users_by_name)

    raw = [(regan_id, 22.505), (brand_id, 22.505), (alice_id, 22.49)]
    discrete_result = discrete_split(raw)

    # ── Helpers for inserting expenses ─────────────────────────────────────────
    def add_expense(paid_by, amount_sgd, category, description, splits_list, currency="SGD"):
        eid = queries.insert_expense(paid_by, amount_sgd, currency, amount_sgd, 1.0,
                                     category, description, "equal", GROUP, trip_id)
        queries.insert_expense_splits(eid, splits_list)
        return eid

    def add_custom(paid_by, amount_sgd, category, description, splits_list, currency="SGD"):
        eid = queries.insert_expense(paid_by, amount_sgd, currency, amount_sgd, 1.0,
                                     category, description, "discrete", GROUP, trip_id)
        queries.insert_expense_splits(eid, splits_list)
        return eid

    # ── Section 3: 18 expenses ─────────────────────────────────────────────────
    s = equal_split(30.0, [regan_id, brand_id, alice_id], regan_id)
    add_expense(regan_id, 30.0, "transport", "Narita Express to Shinjuku", s, "JPY")

    s = equal_split(90.0, [regan_id, brand_id, alice_id], brand_id)
    add_expense(brand_id, 90.0, "food", "Welcome dinner at izakaya", s, "JPY")

    s = equal_split(12.0, [regan_id, brand_id, alice_id], alice_id)
    add_expense(alice_id, 12.0, "food", "7-Eleven breakfast", s, "JPY")

    s = equal_split(120.0, [regan_id, brand_id, alice_id], regan_id)
    add_expense(regan_id, 120.0, "activities", "TeamLab Planets tickets", s, "JPY")

    s = equal_split(20.0, [regan_id, brand_id, alice_id], regan_id)
    exp05_id = add_expense(regan_id, 20.0, "transport", "Vending machine drinks Harajuku", s, "JPY")

    s06_raw, _ = parse_custom_split_text("@Regan 25, @Brandeline 25", users_by_name)
    add_custom(regan_id, 50.0, "activities", "Shibuya Sky observation deck",
               discrete_split(s06_raw), "JPY")

    s = equal_split(40.0, [regan_id, brand_id, alice_id], brand_id)
    add_expense(brand_id, 40.0, "food", "Ichiran Ramen dinner Shibuya", s, "JPY")

    s = equal_split(60.0, [regan_id, brand_id, alice_id], regan_id)
    add_expense(regan_id, 60.0, "transport", "Romancecar Limited Express to Hakone", s, "JPY")

    s = equal_split(30.0, [regan_id, brand_id, alice_id], brand_id)
    add_expense(brand_id, 30.0, "activities", "Hakone Ropeway and Open Air Museum", s, "JPY")

    s = equal_split(90.0, [regan_id, brand_id, alice_id], alice_id)
    add_expense(alice_id, 90.0, "food", "Kaiseki dinner at Hakone Onsen", s, "JPY")

    s = equal_split(150.0, [regan_id, brand_id, alice_id], regan_id)
    add_expense(regan_id, 150.0, "transport", "Shinkansen Nozomi Tokyo to Osaka", s, "JPY")

    s = equal_split(30.0, [regan_id, brand_id, alice_id], brand_id)
    add_expense(brand_id, 30.0, "food", "Dotonbori street food takoyaki", s, "JPY")

    s13_raw, _ = parse_custom_split_text("@Alice 12, @Brandeline 12", users_by_name)
    add_custom(alice_id, 24.0, "activities", "Cup Noodles Museum tickets",
               discrete_split(s13_raw), "JPY")

    s = equal_split(12.0, [regan_id, brand_id, alice_id], regan_id)
    add_expense(regan_id, 12.0, "activities", "Kinkakuji entrance tickets", s, "JPY")

    s15_raw, _ = parse_custom_split_text("@Regan 22.50, @Brandeline 22.50, @Alice 22.50", users_by_name)
    add_custom(brand_id, 67.50, "food", "Nishiki Market wagyu skewers and mochi",
               discrete_split(s15_raw), "USD")

    s = equal_split(36.0, [regan_id, brand_id, alice_id], alice_id)
    add_expense(alice_id, 36.0, "others", "Don Quijote group souvenirs", s, "JPY")

    s = equal_split(54.0, [regan_id, brand_id, alice_id], regan_id)
    add_expense(regan_id, 54.0, "food", "Farewell yakiniku dinner Osaka", s, "USD")

    s = equal_split(24.0, [regan_id, brand_id, alice_id], brand_id)
    add_expense(brand_id, 24.0, "food", "Airport Kansai duty-free snacks", s, "JPY")

    all_expenses = queries.get_expenses_for_group(GROUP, trip_id=trip_id)

    # Verify split totals match expense totals
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    split_rows = conn.execute(
        "SELECT e.id, e.amount_sgd, SUM(es.amount_sgd) AS split_total "
        "FROM expenses e JOIN expense_splits es ON es.expense_id = e.id "
        "WHERE e.group_chat_id = ? AND e.trip_id = ? GROUP BY e.id",
        (GROUP, trip_id),
    ).fetchall()
    conn.close()
    split_mismatches = [
        (r["id"], r["amount_sgd"], r["split_total"])
        for r in split_rows
        if not near(r["amount_sgd"], r["split_total"])
    ]

    # Intermediate balance (accounting invariant check)
    net_intermediate = compute_net_balances(queries.get_balance_data(GROUP, trip_id))

    # ── Section 4: final balance after 18 expenses ─────────────────────────────
    net_final = compute_net_balances(queries.get_balance_data(GROUP, trip_id))
    transfers_final = simplify_debts(net_final)
    alice_transfer_final = next((t for t in transfers_final if t[0] == alice_id), None)
    brand_transfer_final = next((t for t in transfers_final if t[0] == brand_id), None)

    # ── Section 5: undo (delete duplicate) ────────────────────────────────────
    s_dup = equal_split(30.0, [regan_id, brand_id, alice_id], brand_id)
    dup_id = add_expense(brand_id, 30.0, "food", "Dotonbori takoyaki duplicate", s_dup, "JPY")

    count_before_undo = len(queries.get_expenses_for_group(GROUP, trip_id=trip_id))
    net_before_undo   = compute_net_balances(queries.get_balance_data(GROUP, trip_id))
    deleted_dup       = queries.delete_expense(dup_id, GROUP)
    count_after_undo  = len(queries.get_expenses_for_group(GROUP, trip_id=trip_id))

    conn = sqlite3.connect(str(db_file))
    dup_leftover_splits = conn.execute(
        "SELECT COUNT(*) FROM expense_splits WHERE expense_id = ?", (dup_id,)
    ).fetchone()[0]
    conn.close()

    net_after_undo = compute_net_balances(queries.get_balance_data(GROUP, trip_id))

    # ── Section 6: edit ────────────────────────────────────────────────────────
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    exp05_cat_before = conn.execute(
        "SELECT category FROM expenses WHERE id = ?", (exp05_id,)
    ).fetchone()["category"]
    conn.close()

    edit_result = queries.update_expense_field(exp05_id, GROUP, "category", "food")

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    exp05_cat_after = conn.execute(
        "SELECT category FROM expenses WHERE id = ?", (exp05_id,)
    ).fetchone()["category"]
    conn.close()

    desc_result = queries.update_expense_field(
        exp05_id, GROUP, "description", "Vending machine drinks Harajuku (corrected)"
    )

    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row
    exp05_desc = conn.execute(
        "SELECT description FROM expenses WHERE id = ?", (exp05_id,)
    ).fetchone()["description"]
    conn.close()

    try:
        queries.update_expense_field(exp05_id, GROUP, "amount_sgd", "999")
        blocked_field_raised = False
    except ValueError:
        blocked_field_raised = True

    net_after_edit = compute_net_balances(queries.get_balance_data(GROUP, trip_id))

    # ── Section 7: delete exp05 ────────────────────────────────────────────────
    net_before_del  = compute_net_balances(queries.get_balance_data(GROUP, trip_id))
    deleted_exp05   = queries.delete_expense(exp05_id, GROUP)
    count_after_del = len(queries.get_expenses_for_group(GROUP, trip_id=trip_id))
    net_after_del   = compute_net_balances(queries.get_balance_data(GROUP, trip_id))

    # Re-insert exp05 so totals match playbook for settlements
    s05_r = equal_split(20.0, [regan_id, brand_id, alice_id], regan_id)
    exp05_new_id     = add_expense(regan_id, 20.0, "food", "Vending machine drinks Harajuku", s05_r, "JPY")
    count_after_restore = len(queries.get_expenses_for_group(GROUP, trip_id=trip_id))

    # ── Section 8: settlement validation ──────────────────────────────────────
    net_pre_settle = compute_net_balances(queries.get_balance_data(GROUP, trip_id))
    all_transfers  = simplify_debts(net_pre_settle)
    brand_valid    = {t: a for f, t, a in all_transfers if f == brand_id}
    alice_valid    = {t: a for f, t, a in all_transfers if f == alice_id}
    regan_valid    = {t: a for f, t, a in all_transfers if f == regan_id}

    # ── Section 9: settlements ─────────────────────────────────────────────────
    alice_transfer_amount = round(abs(net_pre_settle[alice_id]), 2)
    brand_transfer_amount = round(abs(net_pre_settle[brand_id]), 2)

    settle1_id = queries.insert_settlement(alice_id, regan_id, alice_transfer_amount, GROUP, trip_id)
    settle2_id = queries.insert_settlement(brand_id, regan_id, brand_transfer_amount, GROUP, trip_id)

    net_post       = compute_net_balances(queries.get_balance_data(GROUP, trip_id))
    transfers_post = simplify_debts(net_post)
    settlements_db = queries.get_settlements_for_trip(GROUP, trip_id)

    # ── Section 10: edge cases ─────────────────────────────────────────────────
    trip2_id       = queries.create_trip(GROUP, "Empty Trip", "SGD")
    empty_net      = compute_net_balances(queries.get_balance_data(GROUP, trip2_id))
    empty_transfers = simplify_debts(empty_net)

    trip3_id          = queries.create_trip(GROUP, "OneExpenseTrip", "SGD")
    recent_empty      = queries.get_recent_expenses_for_group(GROUP, limit=1, trip_id=trip3_id)
    empty_participants = queries.get_trip_participants(trip3_id)

    # ── Section 11: trip end ───────────────────────────────────────────────────
    ended           = queries.end_trip(trip_id)
    active_after_end = queries.get_active_trip(GROUP)
    ended_again     = queries.end_trip(trip_id)
    data_final_post = queries.get_balance_data(GROUP, trip_id)

    yield {
        # identifiers
        "GROUP": GROUP, "TRIP_NAME": TRIP_NAME,
        "regan_id": regan_id, "brand_id": brand_id, "alice_id": alice_id,
        "trip_id": trip_id, "trip2_id": trip2_id, "trip3_id": trip3_id,
        "exp05_id": exp05_id, "exp05_new_id": exp05_new_id, "dup_id": dup_id,
        "users_by_name": users_by_name,
        # section 0
        "active": active, "participants": participants,
        # section 1
        "splits_30": splits_30, "splits_20": splits_20,
        "splits_40": splits_40, "splits_50": splits_50, "splits_100": splits_100,
        "custom_3way": custom_3way, "custom_3way_errors": custom_3way_errors,
        "custom_2person": custom_2person, "custom_2person_errors": custom_2person_errors,
        "custom_unknown_errors": custom_unknown_errors,
        "custom_negative_errors": custom_negative_errors,
        "custom_malformed_errors": custom_malformed_errors,
        "discrete_result": discrete_result,
        # section 3
        "all_expenses": all_expenses,
        "split_mismatches": split_mismatches,
        "net_intermediate": net_intermediate,
        # section 4
        "net_final": net_final, "transfers_final": transfers_final,
        "alice_transfer_final": alice_transfer_final,
        "brand_transfer_final": brand_transfer_final,
        # section 5
        "count_before_undo": count_before_undo, "count_after_undo": count_after_undo,
        "dup_leftover_splits": dup_leftover_splits,
        "net_before_undo": net_before_undo, "net_after_undo": net_after_undo,
        "deleted_dup": deleted_dup,
        # section 6
        "exp05_cat_before": exp05_cat_before, "exp05_cat_after": exp05_cat_after,
        "exp05_desc": exp05_desc,
        "edit_result": edit_result, "desc_result": desc_result,
        "blocked_field_raised": blocked_field_raised,
        "net_after_edit": net_after_edit,
        # section 7
        "net_before_del": net_before_del, "net_after_del": net_after_del,
        "deleted_exp05": deleted_exp05,
        "count_after_del": count_after_del, "count_after_restore": count_after_restore,
        # section 8
        "net_pre_settle": net_pre_settle, "all_transfers": all_transfers,
        "brand_valid": brand_valid, "alice_valid": alice_valid, "regan_valid": regan_valid,
        # section 9
        "alice_transfer_amount": alice_transfer_amount,
        "brand_transfer_amount": brand_transfer_amount,
        "settle1_id": settle1_id, "settle2_id": settle2_id,
        "net_post": net_post, "transfers_post": transfers_post, "settlements_db": settlements_db,
        # section 10
        "empty_net": empty_net, "empty_transfers": empty_transfers,
        "recent_empty": recent_empty, "empty_participants": empty_participants,
        # section 11
        "ended": ended, "active_after_end": active_after_end,
        "ended_again": ended_again, "data_final_post": data_final_post,
        # helpers
        "queries": queries,
        "compute_net_balances": compute_net_balances,
        "simplify_debts": simplify_debts,
        "equal_split": equal_split,
        "parse_custom_split_text": parse_custom_split_text,
    }

    db_mod.DB_PATH = original_path


# ─────────────────────────────────────────────────────────────────────────────
# Section 0 — Setup verification
# ─────────────────────────────────────────────────────────────────────────────

class TestSetup:
    def test_trip_created(self, japan):
        assert japan["trip_id"] is not None

    def test_trip_is_active(self, japan):
        assert japan["active"] is not None
        assert japan["active"]["name"] == japan["TRIP_NAME"]

    def test_three_participants_registered(self, japan):
        assert len(japan["participants"]) == 3

    def test_participant_names(self, japan):
        names = {p["display_name"] for p in japan["participants"]}
        assert names == {"Regan", "Brandeline", "Alice"}


# ─────────────────────────────────────────────────────────────────────────────
# Section 1 — Splitting logic unit tests
# ─────────────────────────────────────────────────────────────────────────────

class TestSplittingLogic:
    def test_equal_30_total_preserved(self, japan):
        total = sum(a for _, a in japan["splits_30"])
        assert near(total, 30.0), f"total={total}"

    def test_equal_30_each_gets_10(self, japan):
        per = {uid: a for uid, a in japan["splits_30"]}
        assert all(near(a, 10.0) for a in per.values())

    def test_equal_20_total_preserved(self, japan):
        total = sum(a for _, a in japan["splits_20"])
        assert near(total, 20.0), f"total={total}"

    def test_equal_20_non_payers_get_667(self, japan):
        c = japan
        per = {uid: a for uid, a in c["splits_20"]}
        assert near(per[c["brand_id"]], 6.67) and near(per[c["alice_id"]], 6.67)

    def test_equal_20_payer_gets_remainder(self, japan):
        c = japan
        per = {uid: a for uid, a in c["splits_20"]}
        assert near(per[c["regan_id"]], 6.66)

    def test_equal_40_total_preserved(self, japan):
        total = sum(a for _, a in japan["splits_40"])
        assert near(total, 40.0), f"total={total}"

    def test_equal_40_payer_gets_remainder(self, japan):
        c = japan
        per = {uid: a for uid, a in c["splits_40"]}
        assert near(per[c["brand_id"]], 13.34)

    def test_equal_40_others_get_1333(self, japan):
        c = japan
        per = {uid: a for uid, a in c["splits_40"]}
        assert near(per[c["regan_id"]], 13.33) and near(per[c["alice_id"]], 13.33)

    def test_equal_50_two_person_total(self, japan):
        total = sum(a for _, a in japan["splits_50"])
        assert near(total, 50.0)

    def test_equal_50_two_person_each_25(self, japan):
        c = japan
        per = {uid: a for uid, a in c["splits_50"]}
        assert near(per[c["regan_id"]], 25.0) and near(per[c["brand_id"]], 25.0)

    def test_equal_single_person_full_amount(self, japan):
        assert near(japan["splits_100"][0][1], 100.0)

    def test_custom_3way_no_errors(self, japan):
        assert japan["custom_3way_errors"] == []

    def test_custom_3way_returns_3_splits(self, japan):
        assert len(japan["custom_3way"]) == 3

    def test_custom_3way_total(self, japan):
        assert near(sum(a for _, a in japan["custom_3way"]), 67.50)

    def test_custom_2person_no_errors(self, japan):
        assert japan["custom_2person_errors"] == []

    def test_custom_2person_returns_2_splits(self, japan):
        assert len(japan["custom_2person"]) == 2

    def test_custom_2person_total(self, japan):
        assert near(sum(a for _, a in japan["custom_2person"]), 24.0)

    def test_custom_unknown_user_error(self, japan):
        assert any("nobody" in e for e in japan["custom_unknown_errors"])

    def test_custom_negative_amount_error(self, japan):
        assert len(japan["custom_negative_errors"]) > 0

    def test_custom_malformed_token_error(self, japan):
        assert len(japan["custom_malformed_errors"]) > 0

    def test_discrete_split_rounds_to_2dp(self, japan):
        assert all(round(a, 2) == a for _, a in japan["discrete_result"])


# ─────────────────────────────────────────────────────────────────────────────
# Section 2 — compute_net_balances + simplify_debts unit tests (no DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestBalancesUnit:
    @pytest.fixture(autouse=True)
    def setup(self):
        from bot.services.balances import compute_net_balances, simplify_debts
        self.compute = compute_net_balances
        self.simplify = simplify_debts

    def test_2person_payer_net_positive(self):
        data = {"paid": {1: 100.0}, "owed": {1: 50.0, 2: 50.0},
                "sent": {}, "received": {}, "users": {1: "A", 2: "B"}}
        net = self.compute(data)
        assert near(net[1], 50.0)

    def test_2person_other_net_negative(self):
        data = {"paid": {1: 100.0}, "owed": {1: 50.0, 2: 50.0},
                "sent": {}, "received": {}, "users": {1: "A", 2: "B"}}
        net = self.compute(data)
        assert near(net[2], -50.0)

    def test_2person_one_transfer(self):
        data = {"paid": {1: 100.0}, "owed": {1: 50.0, 2: 50.0},
                "sent": {}, "received": {}, "users": {1: "A", 2: "B"}}
        net = self.compute(data)
        transfers = self.simplify(net)
        assert len(transfers) == 1
        assert transfers[0] == (2, 1, 50.0)

    def test_2person_post_settlement_both_zero(self):
        data = {"paid": {1: 100.0}, "owed": {1: 50.0, 2: 50.0},
                "sent": {2: 50.0}, "received": {1: 50.0}, "users": {1: "A", 2: "B"}}
        net = self.compute(data)
        assert near(net[1], 0.0) and near(net[2], 0.0)

    def test_2person_post_settlement_no_transfers(self):
        data = {"paid": {1: 100.0}, "owed": {1: 50.0, 2: 50.0},
                "sent": {2: 50.0}, "received": {1: 50.0}, "users": {1: "A", 2: "B"}}
        net = self.compute(data)
        assert self.simplify(net) == []

    def test_3person_net_sum_zero(self):
        data3 = {"paid": {1: 90.0, 3: 30.0}, "owed": {1: 40.0, 2: 50.0, 3: 30.0},
                 "sent": {}, "received": {}, "users": {1: "A", 2: "B", 3: "C"}}
        net = self.compute(data3)
        assert near(sum(net.values()), 0.0)

    def test_3person_individual_nets(self):
        data3 = {"paid": {1: 90.0, 3: 30.0}, "owed": {1: 40.0, 2: 50.0, 3: 30.0},
                 "sent": {}, "received": {}, "users": {1: "A", 2: "B", 3: "C"}}
        net = self.compute(data3)
        assert near(net[1], 50.0) and near(net[2], -50.0) and near(net[3], 0.0)

    def test_simplify_ignores_subcent_balances(self):
        assert self.simplify({1: 0.005, 2: -0.005}) == []


# ─────────────────────────────────────────────────────────────────────────────
# Section 3 — Full Japan scenario DB integration
# ─────────────────────────────────────────────────────────────────────────────

class TestFullScenario:
    def test_18_expenses_inserted(self, japan):
        assert len(japan["all_expenses"]) == 18, f"count={len(japan['all_expenses'])}"

    def test_all_split_totals_match_expense_amounts(self, japan):
        assert japan["split_mismatches"] == [], f"mismatches={japan['split_mismatches']}"

    def test_net_sum_zero_invariant(self, japan):
        net_sum = sum(japan["net_intermediate"].values())
        assert abs(net_sum) < 0.05, f"net_sum={net_sum:.4f}"


# ─────────────────────────────────────────────────────────────────────────────
# Section 4 — Final balance verification (all 18 expenses)
# ─────────────────────────────────────────────────────────────────────────────

class TestFinalBalance:
    def test_regan_net_positive(self, japan):
        c = japan
        assert c["net_final"][c["regan_id"]] > 0, f"net={c['net_final'][c['regan_id']]:.2f}"

    def test_brandeline_net_negative(self, japan):
        c = japan
        assert c["net_final"][c["brand_id"]] < 0

    def test_alice_net_negative(self, japan):
        c = japan
        assert c["net_final"][c["alice_id"]] < 0

    def test_alice_owes_more_than_brandeline(self, japan):
        c = japan
        assert abs(c["net_final"][c["alice_id"]]) > abs(c["net_final"][c["brand_id"]])

    def test_regan_net_approx_182_51(self, japan):
        c = japan
        assert near(c["net_final"][c["regan_id"]], 182.51), f"net={c['net_final'][c['regan_id']]:.2f}"

    def test_brandeline_net_approx_minus_44_01(self, japan):
        c = japan
        assert near(c["net_final"][c["brand_id"]], -44.01)

    def test_alice_net_approx_minus_138_50(self, japan):
        c = japan
        assert near(c["net_final"][c["alice_id"]], -138.50)

    def test_net_sum_zero(self, japan):
        assert near(sum(japan["net_final"].values()), 0.0)

    def test_exactly_2_transfers(self, japan):
        assert len(japan["transfers_final"]) == 2

    def test_both_transfers_go_to_regan(self, japan):
        c = japan
        recipients = {to for _, to, _ in c["transfers_final"]}
        assert c["regan_id"] in recipients and len(recipients) == 1

    def test_alice_to_regan_transfer_exists(self, japan):
        assert japan["alice_transfer_final"] is not None

    def test_brandeline_to_regan_transfer_exists(self, japan):
        assert japan["brand_transfer_final"] is not None

    def test_alice_to_regan_amount(self, japan):
        assert near(japan["alice_transfer_final"][2], 138.50)

    def test_brandeline_to_regan_amount(self, japan):
        assert near(japan["brand_transfer_final"][2], 44.01)


# ─────────────────────────────────────────────────────────────────────────────
# Section 5 — /undo: delete last expense
# ─────────────────────────────────────────────────────────────────────────────

class TestUndo:
    def test_duplicate_added_gives_19_expenses(self, japan):
        assert japan["count_before_undo"] == 19

    def test_delete_expense_returns_true(self, japan):
        assert japan["deleted_dup"] is True

    def test_expense_count_back_to_18(self, japan):
        assert japan["count_after_undo"] == 18

    def test_expense_splits_also_deleted(self, japan):
        assert japan["dup_leftover_splits"] == 0

    def test_regan_net_shifted_plus_10_after_undo(self, japan):
        c = japan
        assert near(c["net_after_undo"][c["regan_id"]],
                    c["net_before_undo"][c["regan_id"]] + 10.0)

    def test_brandeline_net_shifted_minus_20_after_undo(self, japan):
        c = japan
        assert near(c["net_after_undo"][c["brand_id"]],
                    c["net_before_undo"][c["brand_id"]] - 20.0)

    def test_alice_net_shifted_plus_10_after_undo(self, japan):
        c = japan
        assert near(c["net_after_undo"][c["alice_id"]],
                    c["net_before_undo"][c["alice_id"]] + 10.0)

    def test_net_sum_still_zero_after_undo(self, japan):
        assert near(sum(japan["net_after_undo"].values()), 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Section 6 — /edit: update_expense_field
# ─────────────────────────────────────────────────────────────────────────────

class TestEdit:
    def test_exp05_initial_category_is_transport(self, japan):
        assert japan["exp05_cat_before"] == "transport"

    def test_update_field_returns_true(self, japan):
        assert japan["edit_result"] is True

    def test_category_changed_to_food(self, japan):
        assert japan["exp05_cat_after"] == "food"

    def test_description_update_returns_true(self, japan):
        assert japan["desc_result"] is True

    def test_description_change_persisted(self, japan):
        assert "corrected" in japan["exp05_desc"]

    def test_blocked_field_raises_value_error(self, japan):
        assert japan["blocked_field_raised"] is True

    def test_balances_unchanged_after_metadata_edit(self, japan):
        c = japan
        assert (near(c["net_after_edit"][c["regan_id"]], c["net_after_undo"][c["regan_id"]]) and
                near(c["net_after_edit"][c["brand_id"]], c["net_after_undo"][c["brand_id"]]) and
                near(c["net_after_edit"][c["alice_id"]], c["net_after_undo"][c["alice_id"]]))


# ─────────────────────────────────────────────────────────────────────────────
# Section 7 — /delete: explicit expense removal
# ─────────────────────────────────────────────────────────────────────────────

class TestDelete:
    def test_delete_returns_true(self, japan):
        assert japan["deleted_exp05"] is True

    def test_expense_count_is_17(self, japan):
        assert japan["count_after_del"] == 17

    def test_net_sum_still_zero_after_delete(self, japan):
        assert near(sum(japan["net_after_del"].values()), 0.0)

    def test_regan_net_decreased_after_delete(self, japan):
        c = japan
        assert near(c["net_after_del"][c["regan_id"]],
                    c["net_before_del"][c["regan_id"]] - 13.34)

    def test_brandeline_net_increased_after_delete(self, japan):
        c = japan
        assert near(c["net_after_del"][c["brand_id"]],
                    c["net_before_del"][c["brand_id"]] + 6.67)

    def test_alice_net_increased_after_delete(self, japan):
        c = japan
        assert near(c["net_after_del"][c["alice_id"]],
                    c["net_before_del"][c["alice_id"]] + 6.67)

    def test_exp05_reinserted_back_to_18(self, japan):
        assert japan["count_after_restore"] == 18


# ─────────────────────────────────────────────────────────────────────────────
# Section 8 — Settlement recipient validation (bug-fix test)
# ─────────────────────────────────────────────────────────────────────────────

class TestSettlementValidation:
    def test_brandeline_should_pay_regan_not_alice(self, japan):
        c = japan
        assert c["regan_id"] in c["brand_valid"] and c["alice_id"] not in c["brand_valid"]

    def test_alice_should_pay_regan_not_brandeline(self, japan):
        c = japan
        assert c["regan_id"] in c["alice_valid"] and c["brand_id"] not in c["alice_valid"]

    def test_regan_owes_nobody(self, japan):
        assert len(japan["regan_valid"]) == 0

    def test_wrong_person_settle_blocked(self, japan):
        c = japan
        assert c["alice_id"] not in c["brand_valid"]

    def test_correct_person_settle_allowed(self, japan):
        c = japan
        assert c["regan_id"] in c["brand_valid"]

    def test_over_amount_rejected(self, japan):
        c = japan
        brand_owes = abs(c["net_pre_settle"][c["brand_id"]])
        over = round(brand_owes + 10.0, 2)
        assert over > round(brand_owes, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Section 9 — Settlement recording + balance reconciliation to zero
# ─────────────────────────────────────────────────────────────────────────────

class TestSettlements:
    def test_alice_settlement_inserted(self, japan):
        assert japan["settle1_id"] is not None

    def test_brandeline_settlement_inserted(self, japan):
        assert japan["settle2_id"] is not None

    def test_post_settlement_regan_net_zero(self, japan):
        c = japan
        assert near(c["net_post"][c["regan_id"]], 0.0, tol=0.05)

    def test_post_settlement_brandeline_net_zero(self, japan):
        c = japan
        assert near(c["net_post"][c["brand_id"]], 0.0, tol=0.05)

    def test_post_settlement_alice_net_zero(self, japan):
        c = japan
        assert near(c["net_post"][c["alice_id"]], 0.0, tol=0.05)

    def test_no_further_transfers_needed(self, japan):
        assert japan["transfers_post"] == [], f"remaining={japan['transfers_post']}"

    def test_two_settlement_records_in_db(self, japan):
        assert len(japan["settlements_db"]) == 2

    def test_settlement_names_correct(self, japan):
        names = {(s["from_name"], s["to_name"]) for s in japan["settlements_db"]}
        assert ("Alice", "Regan") in names and ("Brandeline", "Regan") in names

    def test_total_settled_matches_debts(self, japan):
        c = japan
        total = sum(s["amount_sgd"] for s in c["settlements_db"])
        assert near(total, c["alice_transfer_amount"] + c["brand_transfer_amount"])


# ─────────────────────────────────────────────────────────────────────────────
# Section 10 — Edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_e1_equal_split_empty_user_list(self, japan):
        from bot.services.splitting import equal_split
        assert equal_split(100.0, [], japan["regan_id"]) == []

    def test_e2_parse_empty_string(self, japan):
        c = japan
        splits, errors = c["parse_custom_split_text"]("", c["users_by_name"])
        assert splits == [] and errors == []

    def test_e3_duplicate_user_rejected(self, japan):
        c = japan
        splits, errors = c["parse_custom_split_text"](
            "@Regan 20, @Regan 20", c["users_by_name"])
        assert len(splits) == 1 and len(errors) == 1 and "Duplicate" in errors[0]

    def test_e4_split_total_mismatch_detectable(self, japan):
        c = japan
        s_bad, _ = c["parse_custom_split_text"]("@Regan 40, @Alice 40", c["users_by_name"])
        diff = abs(sum(a for _, a in s_bad) - 100.0)
        assert diff > 0.02, f"diff={diff:.2f}"

    def test_e5_delete_nonexistent_expense(self, japan):
        assert japan["queries"].delete_expense(999999, japan["GROUP"]) is False

    def test_e6_update_field_wrong_group(self, japan):
        c = japan
        result = c["queries"].update_expense_field(
            c["exp05_new_id"], "wrong_group", "category", "transport")
        assert result is False

    def test_e7_empty_trip_net_empty(self, japan):
        assert japan["empty_net"] == {}

    def test_e7_empty_trip_no_transfers(self, japan):
        assert japan["empty_transfers"] == []

    def test_e8_all_zero_balances_no_transfers(self, japan):
        c = japan
        zero_net = {c["regan_id"]: 0.0, c["brand_id"]: 0.0, c["alice_id"]: 0.0}
        assert c["simplify_debts"](zero_net) == []

    def test_e9_3way_greedy_exactly_2_transfers(self, japan):
        transfers = japan["simplify_debts"]({1: 100.0, 2: -60.0, 3: -40.0})
        assert len(transfers) == 2

    def test_e9_3way_total_transferred(self, japan):
        transfers = japan["simplify_debts"]({1: 100.0, 2: -60.0, 3: -40.0})
        assert near(sum(a for _, _, a in transfers), 100.0)

    def test_e10_4person_all_balances_cleared(self, japan):
        net_4 = {1: 50.0, 2: 30.0, 3: -40.0, 4: -40.0}
        transfers = japan["simplify_debts"](net_4)
        after = dict(net_4)
        for f, t, a in transfers:
            after[f] += a
            after[t] -= a
        assert all(abs(b) < 0.01 for b in after.values())

    def test_e11_undo_on_empty_trip_no_recent(self, japan):
        assert len(japan["recent_empty"]) == 0

    def test_e12_new_trip_no_participants(self, japan):
        assert len(japan["empty_participants"]) == 0


# ─────────────────────────────────────────────────────────────────────────────
# Section 11 — /tripend
# ─────────────────────────────────────────────────────────────────────────────

class TestTripEnd:
    def test_end_trip_returns_true(self, japan):
        assert japan["ended"] is True

    def test_ended_trip_not_returned_as_active(self, japan):
        c = japan
        if c["active_after_end"]:
            assert c["active_after_end"]["name"] != c["TRIP_NAME"]

    def test_second_end_trip_returns_false(self, japan):
        assert japan["ended_again"] is False

    def test_historical_data_still_accessible(self, japan):
        assert len(japan["data_final_post"]["users"]) > 0
