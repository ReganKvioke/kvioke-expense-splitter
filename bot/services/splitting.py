"""Splitting logic: equal and discrete (custom) splits."""
from decimal import Decimal, ROUND_HALF_UP


def equal_split(amount_sgd: float, user_ids: list[int], payer_id: int) -> list[tuple[int, float]]:
    """Split amount equally. Remainder cents assigned to payer."""
    n = len(user_ids)
    if n == 0:
        return []

    total = Decimal(str(amount_sgd))
    per_person = (total / n).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    remainder = total - per_person * n

    splits = []
    for uid in user_ids:
        share = per_person
        if uid == payer_id:
            share += remainder
        splits.append((uid, float(share)))
    return splits


def discrete_split(splits_input: list[tuple[int, float]]) -> list[tuple[int, float]]:
    """Validate and return discrete splits as (user_id, amount_sgd) pairs."""
    return [(uid, round(amt, 2)) for uid, amt in splits_input]


def parse_custom_split_text(text: str, users_by_name: dict[str, int]) -> tuple[list[tuple[int, float]], list[str]]:
    """Parse '@alice 10, @bob 20' into splits. Returns (splits, errors)."""
    splits = []
    errors = []

    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) != 2:
            errors.append(f"Cannot parse '{part}' — expected '@name amount'")
            continue

        name, raw_amount = tokens
        name = name.lstrip("@").lower()

        try:
            amount = float(raw_amount)
        except ValueError:
            errors.append(f"Invalid amount '{raw_amount}' for {name}")
            continue

        if amount < 0:
            errors.append(f"Negative amount for {name}")
            continue

        uid = users_by_name.get(name)
        if uid is None:
            errors.append(f"Unknown user '@{name}'")
            continue

        splits.append((uid, amount))

    return splits, errors
