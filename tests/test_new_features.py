"""
Tests for new features added in v1.3+:

  A. _payer_shortcut_keyboard   — keyboard shown when a last payer is remembered
  B. _post_save_keyboard        — "Add another / View balances" buttons after save
  C. _preserve_last_payer       — last-payer keys survive user_data.clear()
  D. _settle_keyboard           — one-tap settle buttons on /balances output
  E. Help text admin gating     — admin-only commands hidden from regular users
  F. get_personal_stats         — /me personal stats DB query
"""
import os
import pytest

from conftest import near


# ─────────────────────────────────────────────────────────────────────────────
# Section A — _payer_shortcut_keyboard
# ─────────────────────────────────────────────────────────────────────────────

class TestPayerShortcutKeyboard:
    @pytest.fixture(autouse=True)
    def _import(self):
        from bot.commands.add import _payer_shortcut_keyboard
        self.keyboard = _payer_shortcut_keyboard

    def _buttons(self, kb):
        return [btn for row in kb.inline_keyboard for btn in row]

    def test_three_buttons_total(self):
        assert len(self._buttons(self.keyboard("Alice"))) == 3

    def test_last_button_contains_payer_name(self):
        labels = [b.text for b in self._buttons(self.keyboard("Alice"))]
        assert any("Alice" in t for t in labels)

    def test_payer_last_callback_present(self):
        cbs = [b.callback_data for b in self._buttons(self.keyboard("Alice"))]
        assert "payer:last" in cbs

    def test_payer_change_callback_present(self):
        cbs = [b.callback_data for b in self._buttons(self.keyboard("Alice"))]
        assert "payer:change" in cbs

    def test_cancel_callback_present(self):
        cbs = [b.callback_data for b in self._buttons(self.keyboard("Alice"))]
        assert "payer:cancel" in cbs

    def test_different_name_reflected(self):
        labels = [b.text for b in self._buttons(self.keyboard("Brandeline"))]
        assert any("Brandeline" in t for t in labels)
        assert not any("Alice" in t for t in labels)


# ─────────────────────────────────────────────────────────────────────────────
# Section B — _post_save_keyboard
# ─────────────────────────────────────────────────────────────────────────────

class TestPostSaveKeyboard:
    @pytest.fixture(autouse=True)
    def _import(self):
        from bot.commands.add import _post_save_keyboard
        self.keyboard = _post_save_keyboard

    def test_single_row(self):
        kb = self.keyboard()
        assert len(kb.inline_keyboard) == 1

    def test_two_buttons_in_row(self):
        kb = self.keyboard()
        assert len(kb.inline_keyboard[0]) == 2

    def test_view_balances_callback(self):
        kb = self.keyboard()
        cbs = [b.callback_data for b in kb.inline_keyboard[0]]
        assert "post_add:balances" in cbs

    def test_add_another_callback_correct(self):
        kb = self.keyboard()
        cbs = [b.callback_data for b in kb.inline_keyboard[0]]
        assert "post_add:add_another" in cbs


# ─────────────────────────────────────────────────────────────────────────────
# Section C — _preserve_last_payer
# ─────────────────────────────────────────────────────────────────────────────

class _MockContext:
    """Minimal stand-in for ContextTypes.DEFAULT_TYPE."""
    def __init__(self, data: dict):
        self.user_data = data


class TestPreserveLastPayer:
    @pytest.fixture(autouse=True)
    def _import(self):
        from bot.commands.add import (
            _preserve_last_payer,
            _KEY_LAST_PAYER_DB_ID,
            _KEY_LAST_PAYER_NAME,
        )
        self.preserve = _preserve_last_payer
        self.ID_KEY = _KEY_LAST_PAYER_DB_ID
        self.NAME_KEY = _KEY_LAST_PAYER_NAME

    def test_preserves_db_id(self):
        ctx = _MockContext({self.ID_KEY: 42, self.NAME_KEY: "Alice", "other": "data"})
        self.preserve(ctx)
        assert ctx.user_data[self.ID_KEY] == 42

    def test_preserves_name(self):
        ctx = _MockContext({self.ID_KEY: 42, self.NAME_KEY: "Alice", "other": "data"})
        self.preserve(ctx)
        assert ctx.user_data[self.NAME_KEY] == "Alice"

    def test_clears_other_keys(self):
        ctx = _MockContext({self.ID_KEY: 42, self.NAME_KEY: "Alice", "stale_amount": 50.0})
        self.preserve(ctx)
        assert "stale_amount" not in ctx.user_data

    def test_no_error_when_no_last_payer(self):
        ctx = _MockContext({"some_key": "value"})
        self.preserve(ctx)  # should not raise
        assert self.ID_KEY not in ctx.user_data

    def test_no_last_payer_clears_everything(self):
        ctx = _MockContext({"some_key": "value"})
        self.preserve(ctx)
        assert ctx.user_data == {}

    def test_zero_db_id_not_preserved(self):
        """A falsy db_id (0) is not preserved — only truthy ids are."""
        ctx = _MockContext({self.ID_KEY: 0, self.NAME_KEY: "Alice"})
        self.preserve(ctx)
        assert self.ID_KEY not in ctx.user_data


# ─────────────────────────────────────────────────────────────────────────────
# Section D — _settle_keyboard (balances.py)
# ─────────────────────────────────────────────────────────────────────────────

class TestSettleKeyboard:
    @pytest.fixture(autouse=True)
    def _import(self):
        from bot.commands.balances import _settle_keyboard
        self.settle_kb = _settle_keyboard

    def _flat_buttons(self, kb):
        return [btn for row in kb.inline_keyboard for btn in row]

    def test_returns_none_when_user_has_no_debts(self):
        transfers = [(2, 1, 50.0), (3, 1, 30.0)]
        result = self.settle_kb(transfers, sender_db_id=4, names={1: "A", 2: "B", 3: "C", 4: "D"})
        assert result is None

    def test_returns_none_for_empty_transfer_list(self):
        assert self.settle_kb([], sender_db_id=1, names={1: "Alice"}) is None

    def test_returns_keyboard_when_user_has_debt(self):
        transfers = [(2, 1, 50.0)]
        result = self.settle_kb(transfers, sender_db_id=2, names={1: "Alice", 2: "Bob"})
        assert result is not None

    def test_only_own_debt_shown(self):
        # users 2 and 3 both owe user 1; only user 2's button should appear
        transfers = [(2, 1, 50.0), (3, 1, 30.0)]
        result = self.settle_kb(transfers, sender_db_id=2, names={1: "A", 2: "B", 3: "C"})
        buttons = self._flat_buttons(result)
        assert len(buttons) == 1

    def test_callback_data_format(self):
        transfers = [(2, 1, 50.0)]
        result = self.settle_kb(transfers, sender_db_id=2, names={1: "Alice", 2: "Bob"})
        cbs = [b.callback_data for b in self._flat_buttons(result)]
        assert "settle_q:2:1:50.00" in cbs

    def test_button_label_contains_recipient_name(self):
        transfers = [(2, 1, 75.5)]
        result = self.settle_kb(transfers, sender_db_id=2, names={1: "Alice", 2: "Bob"})
        labels = [b.text for b in self._flat_buttons(result)]
        assert any("Alice" in t for t in labels)

    def test_button_label_contains_amount(self):
        transfers = [(2, 1, 75.5)]
        result = self.settle_kb(transfers, sender_db_id=2, names={1: "Alice", 2: "Bob"})
        labels = [b.text for b in self._flat_buttons(result)]
        assert any("75.50" in t for t in labels)

    def test_multiple_own_debts_all_shown(self):
        # user 2 owes both user 1 and user 3
        transfers = [(2, 1, 50.0), (2, 3, 20.0)]
        result = self.settle_kb(transfers, sender_db_id=2, names={1: "A", 2: "B", 3: "C"})
        assert len(self._flat_buttons(result)) == 2

    def test_creditor_sees_no_settle_buttons(self):
        # user 1 is owed money, should not get settle buttons
        transfers = [(2, 1, 50.0)]
        result = self.settle_kb(transfers, sender_db_id=1, names={1: "Alice", 2: "Bob"})
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# Section E — Help text admin gating
# ─────────────────────────────────────────────────────────────────────────────

class TestAdminHelpText:
    @pytest.fixture(autouse=True)
    def _import(self):
        from bot.commands.help import _admin_ids, _HELP_USER, _HELP_ADMIN_EXTRA
        self.admin_ids = _admin_ids
        self.user_text = _HELP_USER
        self.admin_extra = _HELP_ADMIN_EXTRA

    def test_admin_ids_parsed(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USER_IDS", "123,456,789")
        assert self.admin_ids() == {"123", "456", "789"}

    def test_admin_ids_whitespace_stripped(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USER_IDS", " 100 , 200 ")
        ids = self.admin_ids()
        assert "100" in ids and "200" in ids

    def test_admin_ids_empty_string_gives_empty_set(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USER_IDS", "")
        assert self.admin_ids() == set()

    def test_non_admin_not_in_admin_set(self, monkeypatch):
        monkeypatch.setenv("ADMIN_USER_IDS", "999")
        assert "111" not in self.admin_ids()

    def test_user_text_excludes_tripdelete(self):
        assert "/tripdelete" not in self.user_text

    def test_user_text_excludes_revoke(self):
        assert "/revoke" not in self.user_text

    def test_user_text_excludes_guestdelete(self):
        assert "/guestdelete" not in self.user_text

    def test_admin_extra_includes_tripdelete(self):
        assert "/tripdelete" in self.admin_extra

    def test_admin_extra_includes_revoke(self):
        assert "/revoke" in self.admin_extra

    def test_admin_extra_includes_orphans(self):
        assert "/orphans" in self.admin_extra

    def test_user_text_includes_standard_commands(self):
        assert "/add" in self.user_text
        assert "/balances" in self.user_text
        assert "/settle" in self.user_text

    def test_combined_text_has_admin_section(self):
        combined = self.user_text + self.admin_extra
        assert "/tripdelete" in combined and "/revoke" in combined


# ─────────────────────────────────────────────────────────────────────────────
# Module-scoped DB fixture for personal stats tests
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def stats_db(tmp_path_factory):
    """
    Scenario:
      - Regan pays SGD 90 (food) split equally 3 ways  → each owes 30
      - Regan pays SGD 30 (transport) split equally 3 ways → each owes 10
      - Brand pays SGD 60 (food) split equally 3 ways  → each owes 20
      - Alice settles 40 SGD → Regan

    Expected per-user stats (using formula: net = paid - owed + sent - received):
      Regan:  paid=120, owed=60 (30+10+20), sent=0,  received=40  → net = 120-60+0-40 = 20
      Brand:  paid=60,  owed=60 (30+10+20), sent=0,  received=0   → net = 0
      Alice:  paid=0,   owed=60 (30+10+20), sent=40, received=0   → net = 0-60+40-0 = -20
    """
    import bot.db.database as db_mod
    from bot.db.schema import init_db
    from bot.db import queries
    from bot.services.splitting import equal_split

    db_file = tmp_path_factory.mktemp("stats") / "test.db"
    original_path = db_mod.DB_PATH
    db_mod.DB_PATH = db_file
    init_db()

    GROUP = "stats_group_001"
    regan_id = queries.upsert_user("tg_regan", "Regan")
    brand_id  = queries.upsert_user("tg_brand", "Brand")
    alice_id  = queries.upsert_user("tg_alice", "Alice")

    trip_id = queries.create_trip(GROUP, "Stats Trip", "SGD")
    queries.add_trip_participants(trip_id, [regan_id, brand_id, alice_id])

    # Regan pays 90 food
    s = equal_split(90.0, [regan_id, brand_id, alice_id], regan_id)
    e1 = queries.insert_expense(regan_id, 90.0, "SGD", 90.0, 1.0, "food", "Dinner", "equal", GROUP, trip_id)
    queries.insert_expense_splits(e1, s)

    # Regan pays 30 transport
    s2 = equal_split(30.0, [regan_id, brand_id, alice_id], regan_id)
    e2 = queries.insert_expense(regan_id, 30.0, "SGD", 30.0, 1.0, "transport", "Taxi", "equal", GROUP, trip_id)
    queries.insert_expense_splits(e2, s2)

    # Brand pays 60 food
    s3 = equal_split(60.0, [regan_id, brand_id, alice_id], brand_id)
    e3 = queries.insert_expense(brand_id, 60.0, "SGD", 60.0, 1.0, "food", "Lunch", "equal", GROUP, trip_id)
    queries.insert_expense_splits(e3, s3)

    # Alice settles 40 → Regan
    queries.insert_settlement(alice_id, regan_id, 40.0, GROUP, trip_id)

    regan_stats = queries.get_personal_stats(GROUP, regan_id, trip_id)
    brand_stats = queries.get_personal_stats(GROUP, brand_id, trip_id)
    alice_stats = queries.get_personal_stats(GROUP, alice_id, trip_id)

    yield {
        "regan_id": regan_id, "brand_id": brand_id, "alice_id": alice_id,
        "trip_id": trip_id, "GROUP": GROUP,
        "regan": regan_stats, "brand": brand_stats, "alice": alice_stats,
        "queries": queries,
    }

    db_mod.DB_PATH = original_path


# ─────────────────────────────────────────────────────────────────────────────
# Section F — get_personal_stats
# ─────────────────────────────────────────────────────────────────────────────

class TestPersonalStats:
    # ── Regan (paid most) ──────────────────────────────────────────────────────

    def test_regan_total_paid(self, stats_db):
        assert near(stats_db["regan"]["total_paid"], 120.0)

    def test_regan_expenses_count(self, stats_db):
        assert stats_db["regan"]["expenses_count"] == 2

    def test_regan_total_owed(self, stats_db):
        # share: 30 + 10 + 20 = 60
        assert near(stats_db["regan"]["total_owed"], 60.0)

    def test_regan_total_received(self, stats_db):
        assert near(stats_db["regan"]["total_received"], 40.0)

    def test_regan_total_sent(self, stats_db):
        assert near(stats_db["regan"]["total_sent"], 0.0)

    def test_regan_net_positive(self, stats_db):
        # 120 - 60 + 0 - 40 = 20
        assert near(stats_db["regan"]["net"], 20.0)

    def test_regan_has_two_categories(self, stats_db):
        cats = {r["category"] for r in stats_db["regan"]["by_category"]}
        assert cats == {"food", "transport"}

    def test_regan_biggest_expense_is_dinner(self, stats_db):
        b = stats_db["regan"]["biggest_expense"]
        assert b is not None
        assert b["description"] == "Dinner"
        assert near(b["amount_sgd"], 90.0)

    # ── Brand (balanced) ──────────────────────────────────────────────────────

    def test_brand_total_paid(self, stats_db):
        assert near(stats_db["brand"]["total_paid"], 60.0)

    def test_brand_expenses_count(self, stats_db):
        assert stats_db["brand"]["expenses_count"] == 1

    def test_brand_total_owed(self, stats_db):
        assert near(stats_db["brand"]["total_owed"], 60.0)

    def test_brand_net_zero(self, stats_db):
        assert near(stats_db["brand"]["net"], 0.0)

    def test_brand_no_settlements(self, stats_db):
        assert near(stats_db["brand"]["total_sent"], 0.0)
        assert near(stats_db["brand"]["total_received"], 0.0)

    # ── Alice (owes, partial settlement) ──────────────────────────────────────

    def test_alice_total_paid(self, stats_db):
        assert near(stats_db["alice"]["total_paid"], 0.0)

    def test_alice_expenses_count(self, stats_db):
        assert stats_db["alice"]["expenses_count"] == 0

    def test_alice_total_owed(self, stats_db):
        assert near(stats_db["alice"]["total_owed"], 60.0)

    def test_alice_total_sent(self, stats_db):
        assert near(stats_db["alice"]["total_sent"], 40.0)

    def test_alice_net_negative(self, stats_db):
        # 0 - 60 + 40 - 0 = -20
        assert near(stats_db["alice"]["net"], -20.0)

    def test_alice_no_biggest_expense(self, stats_db):
        assert stats_db["alice"]["biggest_expense"] is None

    def test_alice_category_breakdown_present(self, stats_db):
        # alice has shares in food and transport
        cats = {r["category"] for r in stats_db["alice"]["by_category"]}
        assert "food" in cats and "transport" in cats

    # ── Net sum invariant ──────────────────────────────────────────────────────

    def test_net_sum_is_zero(self, stats_db):
        total = (
            stats_db["regan"]["net"]
            + stats_db["brand"]["net"]
            + stats_db["alice"]["net"]
        )
        assert near(total, 0.0)

    # ── No active trip: scoping check ─────────────────────────────────────────

    def test_different_trip_returns_zeros(self, stats_db):
        """Stats for a trip the user has no expenses in should be all zeros."""
        q = stats_db["queries"]
        other_trip = q.create_trip(stats_db["GROUP"], "Empty Trip", "SGD")
        s = q.get_personal_stats(stats_db["GROUP"], stats_db["regan_id"], other_trip)
        assert near(s["total_paid"], 0.0)
        assert near(s["total_owed"], 0.0)
        assert s["expenses_count"] == 0
        assert s["biggest_expense"] is None
