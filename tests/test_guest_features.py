"""
New Features — pytest logic verification tests.

Covers (without Telegram):
  - Guest user creation, listing, count, and deletion
  - merge_guest_user: full atomic reassignment across all 4 tables
  - merge_guest_user: trip_participants transfer (INSERT OR IGNORE)
  - merge_guest_user: balance invariant preserved after merge
  - merge_guest_user: no-op on non-guest id (safety guard)
  - merge_guest_user: guest with zero linked records
  - Trip auto-join (add_trip_participants idempotency)
  - /tripjoin: duplicate join is a no-op (INSERT OR IGNORE)
  - get_all_guest_users returns only guests
  - get_guest_linked_count accuracy
  - Per-trip alias management
  - Expression parsing in custom splits

Uses an isolated temp SQLite DB — production DB is never touched.
"""
import sqlite3

import pytest

from conftest import near


# ─────────────────────────────────────────────────────────────────────────────
# Module-scoped fixture: runs all new-feature scenarios once
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def nf(tmp_path_factory):
    """Set up all new-feature scenarios, yield full context."""
    import bot.db.database as db_mod
    from bot.db.schema import init_db
    from bot.db import queries
    from bot.services.splitting import equal_split
    from bot.services.balances import compute_net_balances

    db_file = tmp_path_factory.mktemp("nf") / "test.db"
    original_path = db_mod.DB_PATH
    db_mod.DB_PATH = db_file

    init_db()
    GROUP = "test_group_nf"

    def direct(sql, params=()):
        conn = sqlite3.connect(str(db_file))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # Real users
    regan_id = queries.upsert_user("tg_regan_nf", "Regan")
    alice_id = queries.upsert_user("tg_alice_nf", "Alice")

    # ── Section A: guest user management ──────────────────────────────────────
    brand_guest_id   = queries.create_guest_user("Brandeline")
    guests_a         = queries.get_all_guest_users()
    guest_row_a      = queries.get_user_by_id(brand_guest_id)
    real_row_a       = queries.get_user_by_id(regan_id)
    linked_count_a   = queries.get_guest_linked_count(brand_guest_id)

    temp_guest_id    = queries.create_guest_user("TempGuest")
    deleted_temp     = queries.delete_guest_user(temp_guest_id)
    guests_after_del = queries.get_all_guest_users()

    deleted_real     = queries.delete_guest_user(regan_id)
    real_still_exists = queries.get_user_by_id(regan_id)

    # ── Section B: merge_guest_user full scenario ──────────────────────────────
    trip_id = queries.create_trip(GROUP, "Merge Test Trip", "SGD")
    queries.add_trip_participants(trip_id, [regan_id, alice_id, brand_guest_id])

    # Expense 1: guest pays 90 SGD, equal 3
    s1 = equal_split(90.0, [regan_id, alice_id, brand_guest_id], brand_guest_id)
    e1_id = queries.insert_expense(brand_guest_id, 90.0, "SGD", 90.0, 1.0,
                                    "food", "Dinner paid by guest", "equal", GROUP, trip_id)
    queries.insert_expense_splits(e1_id, s1)

    # Expense 2: Regan pays 60 SGD, equal 3
    s2 = equal_split(60.0, [regan_id, alice_id, brand_guest_id], regan_id)
    e2_id = queries.insert_expense(regan_id, 60.0, "SGD", 60.0, 1.0,
                                    "transport", "Train tickets", "equal", GROUP, trip_id)
    queries.insert_expense_splits(e2_id, s2)

    # Settlement: guest pays Regan 10 SGD partial
    settle_id = queries.insert_settlement(brand_guest_id, regan_id, 10.0, GROUP, trip_id)

    linked_count_b   = queries.get_guest_linked_count(brand_guest_id)
    data_before_b    = queries.get_balance_data(GROUP, trip_id)
    net_before_b     = compute_net_balances(data_before_b)

    brand_real_id = queries.upsert_user("tg_brand_nf", "Brandeline")
    merge_result_b = queries.merge_guest_user(brand_guest_id, brand_real_id)

    guest_after_merge   = queries.get_user_by_id(brand_guest_id)
    guests_after_merge  = queries.get_all_guest_users()
    expense1_paid_by    = direct("SELECT paid_by_user_id FROM expenses WHERE id = ?", (e1_id,))
    split_user_ids_e1   = {r["user_id"] for r in
                           direct("SELECT user_id FROM expense_splits WHERE expense_id = ?", (e1_id,))}
    settle_from         = direct("SELECT from_user_id FROM settlements WHERE id = ?", (settle_id,))
    participants_b      = queries.get_trip_participants(trip_id)
    participant_ids_b   = {p["id"] for p in participants_b}
    data_after_b        = queries.get_balance_data(GROUP, trip_id)
    net_after_b         = compute_net_balances(data_after_b)

    # ── Section C: merge edge cases ────────────────────────────────────────────
    empty_guest_id   = queries.create_guest_user("EmptyGuest")
    real2_id         = queries.upsert_user("tg_real2_nf", "RealUser2")
    result_empty     = queries.merge_guest_user(empty_guest_id, real2_id)
    empty_guest_after = queries.get_user_by_id(empty_guest_id)

    trip2_id         = queries.create_trip(GROUP, "Overlap Trip", "SGD")
    overlap_guest_id = queries.create_guest_user("OverlapGuest")
    queries.add_trip_participants(trip2_id, [regan_id, overlap_guest_id])
    queries.merge_guest_user(overlap_guest_id, regan_id)
    overlap_trip_count = direct(
        "SELECT COUNT(*) AS cnt FROM trip_participants WHERE trip_id = ? AND user_id = ?",
        (trip2_id, regan_id))[0]["cnt"]
    overlap_guest_in_trip = any(
        r["user_id"] == overlap_guest_id
        for r in direct("SELECT user_id FROM trip_participants WHERE trip_id = ?", (trip2_id,)))

    solo_guest_id = queries.create_guest_user("SoloGuest")
    try:
        queries.merge_guest_user(solo_guest_id, 99999)
        merge_nonexistent_raised = False
    except Exception:
        merge_nonexistent_raised = True

    # ── Section D: trip auto-join / /tripjoin DB logic ─────────────────────────
    trip3_id           = queries.create_trip(GROUP, "AutoJoin Trip", "SGD")
    queries.add_trip_participants(trip3_id, [regan_id])
    charlie_id         = queries.upsert_user("tg_charlie_nf", "Charlie")
    participants_d_before = queries.get_trip_participants(trip3_id)

    queries.add_trip_participants(trip3_id, [charlie_id])
    participants_d_after = queries.get_trip_participants(trip3_id)

    queries.add_trip_participants(trip3_id, [charlie_id])
    participants_d_dup = queries.get_trip_participants(trip3_id)
    charlie_count = direct(
        "SELECT COUNT(*) AS cnt FROM trip_participants WHERE trip_id = ? AND user_id = ?",
        (trip3_id, charlie_id))[0]["cnt"]

    active_d = queries.get_active_trip(GROUP)
    queries.end_trip(trip3_id)
    active_after_d = queries.get_active_trip(GROUP)

    queries.add_trip_participants(trip3_id, [alice_id])
    alice_in_ended = direct(
        "SELECT COUNT(*) AS cnt FROM trip_participants WHERE trip_id = ? AND user_id = ?",
        (trip3_id, alice_id))[0]["cnt"]

    # ── Section E: get_guest_linked_count accuracy ─────────────────────────────
    trip4_id       = queries.create_trip(GROUP, "Count Test Trip", "SGD")
    count_guest_id = queries.create_guest_user("CountGuest")
    queries.add_trip_participants(trip4_id, [regan_id, alice_id, count_guest_id])

    s_e = equal_split(30.0, [regan_id, alice_id, count_guest_id], count_guest_id)
    eid1 = queries.insert_expense(count_guest_id, 30.0, "SGD", 30.0, 1.0,
                                   "food", "Exp A", "equal", GROUP, trip4_id)
    queries.insert_expense_splits(eid1, s_e)

    s_f = equal_split(60.0, [regan_id, alice_id, count_guest_id], count_guest_id)
    eid2 = queries.insert_expense(count_guest_id, 60.0, "SGD", 60.0, 1.0,
                                   "food", "Exp B", "equal", GROUP, trip4_id)
    queries.insert_expense_splits(eid2, s_f)

    s_g = equal_split(45.0, [regan_id, alice_id, count_guest_id], regan_id)
    eid3 = queries.insert_expense(regan_id, 45.0, "SGD", 45.0, 1.0,
                                   "food", "Exp C", "equal", GROUP, trip4_id)
    queries.insert_expense_splits(eid3, s_g)

    queries.insert_settlement(count_guest_id, regan_id, 5.0, GROUP, trip4_id)
    queries.insert_settlement(alice_id, count_guest_id, 3.0, GROUP, trip4_id)

    linked_count_e = queries.get_guest_linked_count(count_guest_id)

    # ── Section F: merge balance accuracy end-to-end ──────────────────────────
    data_pre_f  = queries.get_balance_data(GROUP, trip4_id)
    net_pre_f   = compute_net_balances(data_pre_f)

    result_f    = queries.merge_guest_user(count_guest_id, alice_id)

    data_post_f = queries.get_balance_data(GROUP, trip4_id)
    net_post_f  = compute_net_balances(data_post_f)
    count_guest_after_f = queries.get_user_by_id(count_guest_id)

    # ── Section G: per-trip alias management ──────────────────────────────────
    alias_user1_id = queries.upsert_user("tg_alias1_nf", "VeryLongUsername1")
    alias_user2_id = queries.upsert_user("tg_alias2_nf", "VeryLongUsername2")
    alias_user3_id = queries.upsert_user("tg_alias3_nf", "VeryLongUsername3")
    alias_trip_id  = queries.create_trip(GROUP, "Alias Trip", "SGD")
    queries.add_trip_participants(alias_trip_id, [alias_user1_id, alias_user2_id, alias_user3_id])

    queries.set_trip_alias(alias_trip_id, alias_user1_id, "Bob")
    participants_g1 = queries.get_trip_participants(alias_trip_id)
    p1_g1 = next((p for p in participants_g1 if p["id"] == alias_user1_id), None)

    raw_row_g2   = queries.get_user_by_id(alias_user1_id)
    all_users_g3 = queries.get_all_known_users()
    u1_g3        = next((u for u in all_users_g3 if u["id"] == alias_user1_id), None)

    queries.set_trip_alias(alias_trip_id, alias_user2_id, "Carol")
    e_alias = queries.insert_expense_with_splits(
        alias_user1_id, 30.0, "SGD", 30.0, 1.0,
        "food", "Alias test expense", "equal", GROUP,
        equal_split(30.0, [alias_user1_id, alias_user2_id], alias_user1_id),
        alias_trip_id,
    )
    balance_data_g4 = queries.get_balance_data(GROUP, alias_trip_id)
    expenses_g5     = queries.get_expenses_for_trip(alias_trip_id)

    queries.set_trip_alias(alias_trip_id, alias_user1_id, None)
    participants_g6 = queries.get_trip_participants(alias_trip_id)
    p1_g6 = next((p for p in participants_g6 if p["id"] == alias_user1_id), None)

    queries.set_trip_alias(alias_trip_id, alias_user1_id, "Dave")
    g7_conflict_raised = False
    try:
        queries.set_trip_alias(alias_trip_id, alias_user2_id, "Carol")
        queries.set_trip_alias(alias_trip_id, alias_user3_id, "Dave")
    except ValueError:
        g7_conflict_raised = True

    g8_conflict_raised = False
    try:
        queries.set_trip_alias(alias_trip_id, alias_user3_id, "dave")
    except ValueError:
        g8_conflict_raised = True

    g9_no_self_conflict = True
    try:
        queries.set_trip_alias(alias_trip_id, alias_user1_id, "Dave")
    except ValueError:
        g9_no_self_conflict = False

    alias_trip2_id    = queries.create_trip(GROUP, "Alias Trip 2", "SGD")
    queries.add_trip_participants(alias_trip2_id, [alias_user1_id])
    participants_g10  = queries.get_trip_participants(alias_trip2_id)
    p1_g10            = next((p for p in participants_g10 if p["id"] == alias_user1_id), None)

    queries.set_trip_alias(alias_trip_id, alias_user2_id, "Eve")
    queries.insert_settlement(alias_user2_id, alias_user1_id, 5.0, GROUP, alias_trip_id)
    settlements_g11   = queries.get_settlements_for_trip(GROUP, alias_trip_id)

    alias_guest_id    = queries.create_guest_user("LongGuestName")
    queries.add_trip_participants(alias_trip_id, [alias_guest_id])
    queries.set_trip_alias(alias_trip_id, alias_guest_id, "Gus")
    participants_g12  = queries.get_trip_participants(alias_trip_id)
    g_part_g12        = next((p for p in participants_g12 if p["id"] == alias_guest_id), None)

    yield {
        # IDs
        "GROUP": GROUP,
        "regan_id": regan_id, "alice_id": alice_id,
        "brand_guest_id": brand_guest_id, "brand_real_id": brand_real_id,
        "charlie_id": charlie_id,
        "trip_id": trip_id, "trip2_id": trip2_id, "trip3_id": trip3_id,
        "trip4_id": trip4_id,
        "e1_id": e1_id, "settle_id": settle_id,
        # section A
        "guests_a": guests_a,
        "guest_row_a": guest_row_a,
        "real_row_a": real_row_a,
        "linked_count_a": linked_count_a,
        "deleted_temp": deleted_temp,
        "temp_guest_id": temp_guest_id,
        "guests_after_del": guests_after_del,
        "deleted_real": deleted_real,
        "real_still_exists": real_still_exists,
        # section B
        "linked_count_b": linked_count_b,
        "net_before_b": net_before_b,
        "merge_result_b": merge_result_b,
        "guest_after_merge": guest_after_merge,
        "guests_after_merge": guests_after_merge,
        "expense1_paid_by": expense1_paid_by,
        "split_user_ids_e1": split_user_ids_e1,
        "settle_from": settle_from,
        "participant_ids_b": participant_ids_b,
        "net_after_b": net_after_b,
        "data_before_b": data_before_b, "data_after_b": data_after_b,
        # section C
        "result_empty": result_empty,
        "empty_guest_after": empty_guest_after,
        "overlap_trip_count": overlap_trip_count,
        "overlap_guest_in_trip": overlap_guest_in_trip,
        "merge_nonexistent_raised": merge_nonexistent_raised,
        # section D
        "participants_d_before": participants_d_before,
        "participants_d_after": participants_d_after,
        "participants_d_dup": participants_d_dup,
        "charlie_count": charlie_count,
        "active_d": active_d,
        "active_after_d": active_after_d,
        "alice_in_ended": alice_in_ended,
        # section E
        "linked_count_e": linked_count_e,
        # section F
        "net_pre_f": net_pre_f, "net_post_f": net_post_f,
        "result_f": result_f,
        "count_guest_id": count_guest_id,
        "count_guest_after_f": count_guest_after_f,
        "data_before_b_paid": sum(data_before_b["paid"].values()),
        "data_after_b_paid":  sum(data_after_b["paid"].values()),
        # section G
        "alias_user1_id": alias_user1_id,
        "alias_user2_id": alias_user2_id,
        "alias_user3_id": alias_user3_id,
        "alias_trip_id": alias_trip_id,
        "p1_g1": p1_g1,
        "raw_row_g2": raw_row_g2,
        "u1_g3": u1_g3,
        "balance_data_g4": balance_data_g4,
        "expenses_g5": expenses_g5,
        "p1_g6": p1_g6,
        "g7_conflict_raised": g7_conflict_raised,
        "g8_conflict_raised": g8_conflict_raised,
        "g9_no_self_conflict": g9_no_self_conflict,
        "p1_g10": p1_g10,
        "settlements_g11": settlements_g11,
        "g_part_g12": g_part_g12,
        # helpers
        "queries": queries,
    }

    db_mod.DB_PATH = original_path


# ─────────────────────────────────────────────────────────────────────────────
# Section A — Guest user management
# ─────────────────────────────────────────────────────────────────────────────

class TestGuestUserManagement:
    def test_create_guest_returns_positive_int(self, nf):
        assert isinstance(nf["brand_guest_id"], int) and nf["brand_guest_id"] > 0

    def test_get_all_guests_contains_new_guest(self, nf):
        ids = [g["id"] for g in nf["guests_a"]]
        assert nf["brand_guest_id"] in ids

    def test_real_users_not_in_guests(self, nf):
        ids = [g["id"] for g in nf["guests_a"]]
        assert nf["regan_id"] not in ids and nf["alice_id"] not in ids

    def test_guest_is_guest_flag_set(self, nf):
        assert nf["guest_row_a"] is not None and nf["guest_row_a"]["is_guest"] == 1

    def test_real_user_is_guest_flag_zero(self, nf):
        assert nf["real_row_a"] is not None and nf["real_row_a"]["is_guest"] == 0

    def test_fresh_guest_zero_expenses_paid(self, nf):
        assert nf["linked_count_a"]["expenses_paid"] == 0

    def test_fresh_guest_zero_splits(self, nf):
        assert nf["linked_count_a"]["splits"] == 0

    def test_fresh_guest_zero_settlements(self, nf):
        assert nf["linked_count_a"]["settlements"] == 0

    def test_delete_guest_with_no_data_returns_true(self, nf):
        assert nf["deleted_temp"] is True

    def test_deleted_guest_no_longer_in_list(self, nf):
        ids = [g["id"] for g in nf["guests_after_del"]]
        assert nf["temp_guest_id"] not in ids

    def test_delete_real_user_returns_false(self, nf):
        assert nf["deleted_real"] is False

    def test_real_user_still_exists_after_failed_delete(self, nf):
        assert nf["real_still_exists"] is not None


# ─────────────────────────────────────────────────────────────────────────────
# Section B — merge_guest_user: full scenario
# ─────────────────────────────────────────────────────────────────────────────

class TestMergeGuestUser:
    def test_guest_has_1_expense_before_merge(self, nf):
        assert nf["linked_count_b"]["expenses_paid"] == 1

    def test_guest_appears_in_splits_before_merge(self, nf):
        assert nf["linked_count_b"]["splits"] >= 1

    def test_guest_has_1_settlement_before_merge(self, nf):
        assert nf["linked_count_b"]["settlements"] == 1

    def test_net_sum_zero_before_merge(self, nf):
        assert near(sum(nf["net_before_b"].values()), 0.0)

    def test_merge_returns_expenses_count(self, nf):
        assert nf["merge_result_b"]["expenses"] >= 1

    def test_merge_returns_splits_count(self, nf):
        assert nf["merge_result_b"]["splits"] >= 1

    def test_merge_returns_settlements_count(self, nf):
        assert nf["merge_result_b"]["settlements"] >= 1

    def test_guest_row_deleted_after_merge(self, nf):
        assert nf["guest_after_merge"] is None

    def test_guest_not_in_list_after_merge(self, nf):
        ids = [g["id"] for g in nf["guests_after_merge"]]
        assert nf["brand_guest_id"] not in ids

    def test_expense_paid_by_reassigned_to_real_user(self, nf):
        rows = nf["expense1_paid_by"]
        assert rows and rows[0]["paid_by_user_id"] == nf["brand_real_id"]

    def test_guest_id_gone_from_splits(self, nf):
        assert nf["brand_guest_id"] not in nf["split_user_ids_e1"]

    def test_real_id_present_in_splits(self, nf):
        assert nf["brand_real_id"] in nf["split_user_ids_e1"]

    def test_settlement_from_user_reassigned(self, nf):
        rows = nf["settle_from"]
        assert rows and rows[0]["from_user_id"] == nf["brand_real_id"]

    def test_real_brand_added_to_trip_participants(self, nf):
        assert nf["brand_real_id"] in nf["participant_ids_b"]

    def test_guest_id_removed_from_trip_participants(self, nf):
        assert nf["brand_guest_id"] not in nf["participant_ids_b"]

    def test_net_sum_zero_after_merge(self, nf):
        assert near(sum(nf["net_after_b"].values()), 0.0)

    def test_total_paid_unchanged_after_merge(self, nf):
        assert near(nf["data_before_b_paid"], nf["data_after_b_paid"])


# ─────────────────────────────────────────────────────────────────────────────
# Section C — merge_guest_user: edge cases
# ─────────────────────────────────────────────────────────────────────────────

class TestMergeGuestEdgeCases:
    def test_merge_empty_guest_returns_zero_expenses(self, nf):
        assert nf["result_empty"]["expenses"] == 0

    def test_merge_empty_guest_returns_zero_splits(self, nf):
        assert nf["result_empty"]["splits"] == 0

    def test_merge_empty_guest_deletes_guest(self, nf):
        assert nf["empty_guest_after"] is None

    def test_no_duplicate_trip_participant_after_merge_into_existing(self, nf):
        assert nf["overlap_trip_count"] == 1

    def test_overlap_guest_removed_from_trip(self, nf):
        assert not nf["overlap_guest_in_trip"]

    def test_merge_nonexistent_user_no_python_exception(self, nf):
        assert not nf["merge_nonexistent_raised"]


# ─────────────────────────────────────────────────────────────────────────────
# Section D — Trip auto-join / /tripjoin DB logic
# ─────────────────────────────────────────────────────────────────────────────

class TestTripAutoJoin:
    def test_charlie_not_in_trip_initially(self, nf):
        ids = {p["id"] for p in nf["participants_d_before"]}
        assert nf["charlie_id"] not in ids

    def test_charlie_added_to_trip(self, nf):
        ids = {p["id"] for p in nf["participants_d_after"]}
        assert nf["charlie_id"] in ids

    def test_participant_count_increased_by_1(self, nf):
        assert len(nf["participants_d_after"]) == len(nf["participants_d_before"]) + 1

    def test_duplicate_add_is_idempotent(self, nf):
        assert len(nf["participants_d_dup"]) == len(nf["participants_d_after"])

    def test_only_one_row_for_charlie_in_trip(self, nf):
        assert nf["charlie_count"] == 1

    def test_get_active_trip_returns_trip_before_end(self, nf):
        assert nf["active_d"] is not None

    def test_ended_trip_not_returned_as_active(self, nf):
        c = nf
        if c["active_after_d"]:
            assert c["active_after_d"]["id"] != c["trip3_id"]

    def test_add_participants_on_ended_trip_works(self, nf):
        assert nf["alice_in_ended"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Section E — get_guest_linked_count accuracy
# ─────────────────────────────────────────────────────────────────────────────

class TestGuestLinkedCount:
    def test_expenses_paid_equals_2(self, nf):
        assert nf["linked_count_e"]["expenses_paid"] == 2

    def test_splits_equals_3(self, nf):
        assert nf["linked_count_e"]["splits"] == 3

    def test_settlements_equals_2(self, nf):
        assert nf["linked_count_e"]["settlements"] == 2


# ─────────────────────────────────────────────────────────────────────────────
# Section F — merge_guest_user: balance accuracy end-to-end
# ─────────────────────────────────────────────────────────────────────────────

class TestMergeBalanceAccuracy:
    def test_net_sum_zero_before_merge(self, nf):
        assert near(sum(nf["net_pre_f"].values()), 0.0)

    def test_merge_transferred_2_expenses(self, nf):
        assert nf["result_f"]["expenses"] == 2

    def test_merge_transferred_3_splits(self, nf):
        assert nf["result_f"]["splits"] == 3

    def test_merge_transferred_2_settlements(self, nf):
        assert nf["result_f"]["settlements"] == 2

    def test_net_sum_zero_after_merge(self, nf):
        assert near(sum(nf["net_post_f"].values()), 0.0)

    def test_count_guest_deleted(self, nf):
        assert nf["count_guest_after_f"] is None


# ─────────────────────────────────────────────────────────────────────────────
# Section G — Per-trip alias management
# ─────────────────────────────────────────────────────────────────────────────

class TestTripAlias:
    def test_set_alias_shown_in_participants(self, nf):
        p1 = nf["p1_g1"]
        assert p1 is not None and p1["display_name"] == "Bob"

    def test_get_user_by_id_unaffected_by_alias(self, nf):
        assert nf["raw_row_g2"]["display_name"] == "VeryLongUsername1"

    def test_get_all_known_users_unaffected_by_alias(self, nf):
        u1 = nf["u1_g3"]
        assert u1 is not None and u1["display_name"] == "VeryLongUsername1"

    def test_balance_data_uses_alias_user1(self, nf):
        bd = nf["balance_data_g4"]
        assert bd["users"].get(nf["alias_user1_id"]) == "Bob"

    def test_balance_data_uses_alias_user2(self, nf):
        bd = nf["balance_data_g4"]
        assert bd["users"].get(nf["alias_user2_id"]) == "Carol"

    def test_expenses_paid_by_name_uses_alias(self, nf):
        expenses = nf["expenses_g5"]
        assert expenses and expenses[0]["paid_by_name"] == "Bob"

    def test_clear_alias_falls_back_to_display_name(self, nf):
        p1 = nf["p1_g6"]
        assert p1 is not None and p1["display_name"] == "VeryLongUsername1"

    def test_duplicate_alias_in_trip_raises_value_error(self, nf):
        assert nf["g7_conflict_raised"] is True

    def test_duplicate_alias_case_insensitive_raises_value_error(self, nf):
        assert nf["g8_conflict_raised"] is True

    def test_resetting_same_alias_no_conflict(self, nf):
        assert nf["g9_no_self_conflict"] is True

    def test_alias_is_trip_isolated(self, nf):
        p1 = nf["p1_g10"]
        assert p1 is not None and p1["display_name"] == "VeryLongUsername1"

    def test_settlement_from_name_uses_alias(self, nf):
        s = nf["settlements_g11"]
        assert s and s[0]["from_name"] == "Eve"

    def test_settlement_to_name_uses_alias(self, nf):
        s = nf["settlements_g11"]
        assert s and s[0]["to_name"] == "Dave"

    def test_guest_trip_alias_set_correctly(self, nf):
        g = nf["g_part_g12"]
        assert g is not None and g["display_name"] == "Gus"


# ─────────────────────────────────────────────────────────────────────────────
# Section H — Expression parsing in custom splits (pure, no DB)
# ─────────────────────────────────────────────────────────────────────────────

class TestExpressionParsing:
    @pytest.fixture(autouse=True)
    def _imports(self):
        from bot.services.splitting import safe_eval_expr, parse_custom_split_text
        self.eval = safe_eval_expr
        self.parse = parse_custom_split_text
        self.users = {"alice": 1, "bob": 2, "charlie": 3}

    # safe_eval_expr — valid expressions
    def test_h1a_plain_number(self):
        assert near(self.eval("50"), 50.0)

    def test_h1b_division(self):
        assert near(self.eval("100/5"), 20.0)

    def test_h1c_multiplication(self):
        assert near(self.eval("100/5*2"), 40.0)

    def test_h1d_addition(self):
        assert near(self.eval("30+20"), 50.0)

    def test_h1e_subtraction(self):
        assert near(self.eval("80-30"), 50.0)

    def test_h1f_parentheses(self):
        assert near(self.eval("(10+40)*2"), 100.0)

    def test_h1g_decimal_operands(self):
        assert near(self.eval("33.33+33.33"), 66.66)

    def test_h1h_spaces_in_expr(self):
        assert near(self.eval("100 / 5 * 2"), 40.0)

    # safe_eval_expr — rejects
    def test_h2a_division_by_zero(self):
        with pytest.raises(ZeroDivisionError):
            self.eval("10/0")

    def test_h2b_exponentiation_rejected(self):
        with pytest.raises(ValueError):
            self.eval("2**10")

    def test_h2c_floor_division_rejected(self):
        with pytest.raises(ValueError):
            self.eval("10//3")

    def test_h2d_modulo_rejected(self):
        with pytest.raises(ValueError):
            self.eval("10%3")

    def test_h2e_injection_rejected(self):
        with pytest.raises(ValueError):
            self.eval("__import__('os')")

    def test_h2f_semicolon_injection_rejected(self):
        with pytest.raises(ValueError):
            self.eval("1+1; import os")

    def test_h2g_empty_expression_rejected(self):
        with pytest.raises(ValueError):
            self.eval("")

    def test_h2h_operator_only_rejected(self):
        with pytest.raises(ValueError):
            self.eval("+")

    def test_h2i_unbalanced_paren_rejected(self):
        with pytest.raises(ValueError):
            self.eval("(10+5")

    def test_h2j_too_long_expression_rejected(self):
        with pytest.raises(ValueError):
            self.eval("1+" * 26 + "1")  # >50 chars

    # parse_custom_split_text — expressions
    def test_h3a_two_person_expr_no_errors(self):
        _, errs = self.parse("@alice 100/5*2, @bob 100/5*2", self.users)
        assert errs == []

    def test_h3b_alice_share_40(self):
        splits, _ = self.parse("@alice 100/5*2, @bob 100/5*2", self.users)
        assert near(splits[0][1], 40.0)

    def test_h3c_bob_share_40(self):
        splits, _ = self.parse("@alice 100/5*2, @bob 100/5*2", self.users)
        assert near(splits[1][1], 40.0)

    def test_h3d_three_way_third_no_errors(self):
        _, errs = self.parse("@alice 100/3, @bob 100/3, @charlie 100/3", self.users)
        assert errs == []

    def test_h3e_three_way_each_share_approx_3333(self):
        splits, _ = self.parse("@alice 100/3, @bob 100/3, @charlie 100/3", self.users)
        assert all(near(amt, 33.33) for _, amt in splits)

    def test_h3f_three_way_total_within_tolerance(self):
        splits, _ = self.parse("@alice 100/3, @bob 100/3, @charlie 100/3", self.users)
        assert near(sum(a for _, a in splits), 100.0, tol=0.02)

    def test_h3g_spaces_inside_expression_allowed(self):
        splits, errs = self.parse("@alice 100 / 5 * 2, @bob 100 / 5 * 2", self.users)
        assert errs == [] and near(splits[0][1], 40.0)

    def test_h3h_single_person_split_allowed(self):
        splits, errs = self.parse("@alice 50", self.users)
        assert errs == [] and len(splits) == 1 and near(splits[0][1], 50.0)

    # parse_custom_split_text — error paths
    def test_h4a_division_by_zero_error(self):
        _, errs = self.parse("@alice 10/0", self.users)
        assert len(errs) == 1 and "zero" in errs[0].lower()

    def test_h4b_exponentiation_error(self):
        _, errs = self.parse("@alice 2**10", self.users)
        assert len(errs) == 1

    def test_h4c_negative_result_error(self):
        _, errs = self.parse("@alice -50", self.users)
        assert len(errs) == 1

    def test_h4d_zero_amount_error(self):
        _, errs = self.parse("@alice 0", self.users)
        assert len(errs) == 1

    def test_h4e_missing_at_prefix_error(self):
        _, errs = self.parse("alice 50", self.users)
        assert len(errs) == 1

    def test_h4f_unknown_user_error(self):
        _, errs = self.parse("@nobody 50", self.users)
        assert len(errs) == 1 and "unknown" in errs[0].lower()

    def test_h4g_duplicate_user_error(self):
        _, errs = self.parse("@alice 50, @alice 30", self.users)
        assert len(errs) == 1 and "duplicate" in errs[0].lower()

    def test_h4h_missing_amount_error(self):
        _, errs = self.parse("@alice", self.users)
        assert len(errs) == 1
