"""
Tests for natural language category detection (v1.5+):

  A. infer_category  — keyword-based category inference from description
  B. _parse_args     — quickadd parser with explicit and inferred categories
"""
import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Section A — infer_category
# ─────────────────────────────────────────────────────────────────────────────

class TestInferCategory:
    @pytest.fixture(autouse=True)
    def _import(self):
        from bot.utils.constants import infer_category
        self.infer = infer_category

    # ── Food ─────────────────────────────────────────────────────────────────

    def test_food_lunch(self):
        assert self.infer("lunch at hawker centre") == "food"

    def test_food_dinner(self):
        assert self.infer("dinner at restaurant") == "food"

    def test_food_breakfast(self):
        assert self.infer("breakfast toast and coffee") == "food"

    def test_food_ramen(self):
        assert self.infer("ramen near the station") == "food"

    def test_food_coffee(self):
        assert self.infer("starbucks coffee") == "food"

    def test_food_sushi(self):
        assert self.infer("sushi and sashimi dinner") == "food"

    def test_food_hawker(self):
        assert self.infer("chicken rice at hawker") == "food"

    def test_food_buffet(self):
        assert self.infer("hotel buffet breakfast") == "food"

    def test_food_boba(self):
        assert self.infer("boba tea after shopping") == "food"

    def test_food_kebab(self):
        assert self.infer("kebab from street stall") == "food"

    # ── Transport ─────────────────────────────────────────────────────────────

    def test_transport_grab(self):
        assert self.infer("grab to hotel") == "transport"

    def test_transport_taxi(self):
        assert self.infer("taxi from airport to city") == "transport"

    def test_transport_mrt(self):
        assert self.infer("mrt topup") == "transport"

    def test_transport_bus(self):
        assert self.infer("bus fare downtown") == "transport"

    def test_transport_petrol(self):
        assert self.infer("petrol for rental car") == "transport"

    def test_transport_scooter(self):
        assert self.infer("scooter rental for the day") == "transport"

    def test_transport_shinkansen(self):
        assert self.infer("shinkansen tokyo to kyoto") == "transport"

    # ── Accommodation ─────────────────────────────────────────────────────────

    def test_accommodation_hotel(self):
        assert self.infer("hotel stay 2 nights") == "accommodation"

    def test_accommodation_airbnb(self):
        assert self.infer("airbnb booking city centre") == "accommodation"

    def test_accommodation_hostel(self):
        assert self.infer("hostel dorm room") == "accommodation"

    def test_accommodation_ryokan(self):
        assert self.infer("ryokan in kyoto") == "accommodation"

    def test_accommodation_villa(self):
        assert self.infer("villa for 3 nights") == "accommodation"

    # ── Sightseeing ──────────────────────────────────────────────────────────

    def test_sightseeing_museum(self):
        assert self.infer("museum entrance fee") == "sightseeing"

    def test_sightseeing_temple(self):
        assert self.infer("temple admission ticket") == "sightseeing"

    def test_sightseeing_castle(self):
        assert self.infer("castle tour ticket") == "sightseeing"

    def test_sightseeing_zoo(self):
        assert self.infer("zoo tickets for two") == "sightseeing"

    def test_sightseeing_aquarium(self):
        assert self.infer("aquarium entrance") == "sightseeing"

    def test_sightseeing_guided_tour(self):
        assert self.infer("guided tour of old town") == "sightseeing"

    def test_sightseeing_multiple_hits(self):
        assert self.infer("temple entrance ticket") == "sightseeing"

    # ── Activities ────────────────────────────────────────────────────────────

    def test_activities_spa(self):
        assert self.infer("spa massage session") == "activities"

    def test_activities_diving(self):
        assert self.infer("scuba diving lesson") == "activities"

    def test_activities_kayak(self):
        assert self.infer("kayaking on the river") == "activities"

    def test_activities_concert(self):
        assert self.infer("concert tickets tonight") == "activities"

    def test_activities_karaoke(self):
        assert self.infer("karaoke session ktv") == "activities"

    def test_activities_cinema(self):
        assert self.infer("movie cinema evening") == "activities"

    def test_activities_escape_room(self):
        assert self.infer("escape room challenge") == "activities"

    # ── Groceries ─────────────────────────────────────────────────────────────

    def test_groceries_supermarket(self):
        assert self.infer("supermarket run for snacks") == "groceries"

    def test_groceries_convenience(self):
        assert self.infer("convenience store water and snacks") == "groceries"

    def test_groceries_donki(self):
        assert self.infer("donki shopping haul") == "groceries"

    def test_groceries_souvenirs(self):
        assert self.infer("souvenir gifts for family") == "groceries"

    def test_groceries_pharmacy(self):
        assert self.infer("pharmacy medicine") == "groceries"

    # ── Flight ────────────────────────────────────────────────────────────────

    def test_flight_explicit(self):
        assert self.infer("flight SIN to HND") == "flight"

    def test_flight_baggage(self):
        assert self.infer("checked baggage fee") == "flight"

    def test_flight_airline(self):
        assert self.infer("airasia booking") == "flight"

    def test_flight_lounge(self):
        assert self.infer("airport lounge access") == "flight"

    def test_flight_upgrade(self):
        assert self.infer("seat upgrade on jetstar") == "flight"

    # ── Others (fallback) ────────────────────────────────────────────────────

    def test_others_no_keywords(self):
        assert self.infer("random thing that matches nothing") == "others"

    def test_others_empty_description(self):
        assert self.infer("") == "others"

    def test_others_single_unrecognised_word(self):
        assert self.infer("xyzzy") == "others"

    def test_others_numbers_only(self):
        assert self.infer("12345 67890") == "others"

    # ── Multi-keyword boost ───────────────────────────────────────────────────

    def test_most_keywords_wins(self):
        # "dinner" and "hawker" both point to food — should beat a single transport keyword
        assert self.infer("grab to dinner at hawker") == "food"

    def test_case_insensitive(self):
        assert self.infer("LUNCH at HAWKER") == "food"

    def test_mixed_case(self):
        assert self.infer("Taxi Ride From Hotel") == "transport"


# ─────────────────────────────────────────────────────────────────────────────
# Section B — _parse_args (quickadd parser)
# ─────────────────────────────────────────────────────────────────────────────

class TestParseArgs:
    @pytest.fixture(autouse=True)
    def _import(self):
        from bot.commands.quickadd import _parse_args
        self.parse = _parse_args

    def _tokens(self, s: str) -> list[str]:
        return s.split()

    # ── Backward compatibility: explicit category ─────────────────────────────

    def test_explicit_category_food(self):
        r = self.parse(self._tokens("50 food lunch at hawker"))
        assert r is not None
        assert r["category"] == "food"
        assert r["description"] == "lunch at hawker"

    def test_explicit_category_transport(self):
        r = self.parse(self._tokens("30 transport grab ride"))
        assert r is not None
        assert r["category"] == "transport"

    def test_explicit_category_with_currency(self):
        r = self.parse(self._tokens("5000 JPY food ramen dinner"))
        assert r is not None
        assert r["currency"] == "JPY"
        assert r["category"] == "food"
        assert r["description"] == "ramen dinner"

    def test_explicit_category_with_payer(self):
        r = self.parse(self._tokens("@Alice 50 food lunch"))
        assert r is not None
        assert r["payer_name"] == "Alice"
        assert r["category"] == "food"

    def test_explicit_all_fields(self):
        r = self.parse(self._tokens("@Bran 50 USD food lunch at hawker"))
        assert r is not None
        assert r["payer_name"] == "Bran"
        assert r["amount"] == 50.0
        assert r["currency"] == "USD"
        assert r["category"] == "food"
        assert r["description"] == "lunch at hawker"

    # ── Inferred category ─────────────────────────────────────────────────────

    def test_inferred_food_from_description(self):
        r = self.parse(self._tokens("50 lunch at hawker centre"))
        assert r is not None
        assert r["category"] == "food"
        assert r["description"] == "lunch at hawker centre"

    def test_inferred_transport_from_grab(self):
        r = self.parse(self._tokens("15 grab to hotel"))
        assert r is not None
        assert r["category"] == "transport"
        assert r["description"] == "grab to hotel"

    def test_inferred_sightseeing_from_temple(self):
        r = self.parse(self._tokens("500 JPY temple entrance fee"))
        assert r is not None
        assert r["category"] == "sightseeing"

    def test_inferred_activities_from_spa(self):
        r = self.parse(self._tokens("80 spa massage session"))
        assert r is not None
        assert r["category"] == "activities"

    def test_inferred_others_fallback(self):
        r = self.parse(self._tokens("50 completely random stuff"))
        assert r is not None
        assert r["category"] == "others"

    def test_inferred_with_payer(self):
        r = self.parse(self._tokens("@Alice 30 dinner at bistro"))
        assert r is not None
        assert r["payer_name"] == "Alice"
        assert r["category"] == "food"

    def test_inferred_with_currency(self):
        r = self.parse(self._tokens("5000 JPY ramen dinner"))
        assert r is not None
        assert r["currency"] == "JPY"
        assert r["category"] == "food"

    def test_inferred_full_description_preserved(self):
        r = self.parse(self._tokens("50 lunch at hawker centre after beach"))
        assert r is not None
        assert r["description"] == "lunch at hawker centre after beach"

    # ── Amount and currency parsing ───────────────────────────────────────────

    def test_amount_parsed_correctly(self):
        r = self.parse(self._tokens("123.45 dinner at restaurant"))
        assert r is not None
        assert r["amount"] == pytest.approx(123.45)

    def test_currency_defaults_to_sgd_when_not_explicit(self):
        r = self.parse(self._tokens("50 dinner"))
        assert r is not None
        assert r["currency"] == "SGD"
        assert r["currency_explicit"] is False

    def test_explicit_currency_flagged(self):
        r = self.parse(self._tokens("50 USD dinner"))
        assert r is not None
        assert r["currency"] == "USD"
        assert r["currency_explicit"] is True

    # ── Invalid inputs ────────────────────────────────────────────────────────

    def test_no_tokens_returns_none(self):
        assert self.parse([]) is None

    def test_amount_only_returns_none(self):
        assert self.parse(["50"]) is None

    def test_negative_amount_returns_none(self):
        assert self.parse(self._tokens("-10 food dinner")) is None

    def test_zero_amount_returns_none(self):
        assert self.parse(self._tokens("0 food dinner")) is None

    def test_non_numeric_amount_returns_none(self):
        assert self.parse(self._tokens("abc food dinner")) is None

    def test_explicit_category_with_no_description_returns_none(self):
        # If user types explicit category but no description after it
        assert self.parse(self._tokens("50 food")) is None

    def test_amount_and_currency_only_returns_none(self):
        assert self.parse(self._tokens("50 USD")) is None
