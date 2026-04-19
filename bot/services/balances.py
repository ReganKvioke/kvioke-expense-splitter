"""Net balance calculation and greedy settlement simplification."""


def compute_net_balances(data: dict) -> dict[int, float]:
    """
    net[user_id] = paid - owed - sent + received
    Positive = others owe them; Negative = they owe others.
    """
    user_ids = set(data["users"].keys())
    # also include anyone in paid/owed/sent/received that might not be in users yet
    for d in (data["paid"], data["owed"], data["sent"], data["received"]):
        user_ids.update(d.keys())

    net = {}
    for uid in user_ids:
        net[uid] = (
            data["paid"].get(uid, 0.0)
            - data["owed"].get(uid, 0.0)
            + data["sent"].get(uid, 0.0)
            - data["received"].get(uid, 0.0)
        )
    return net


def simplify_debts(net: dict[int, float]) -> list[tuple[int, int, float]]:
    """
    Greedy debt simplification.
    Returns list of (from_user_id, to_user_id, amount) transfers.
    """
    THRESHOLD = 0.01

    debtors = sorted(
        [(uid, -bal) for uid, bal in net.items() if bal < -THRESHOLD],
        key=lambda x: x[1], reverse=True,
    )
    creditors = sorted(
        [(uid, bal) for uid, bal in net.items() if bal > THRESHOLD],
        key=lambda x: x[1], reverse=True,
    )

    transfers = []
    i, j = 0, 0
    debtors = [[uid, amt] for uid, amt in debtors]
    creditors = [[uid, amt] for uid, amt in creditors]

    while i < len(debtors) and j < len(creditors):
        debtor_id, debt = debtors[i]
        creditor_id, credit = creditors[j]

        transfer = min(debt, credit)
        if transfer > THRESHOLD:
            transfers.append((debtor_id, creditor_id, round(transfer, 2)))

        debtors[i][1] -= transfer
        creditors[j][1] -= transfer

        if debtors[i][1] < THRESHOLD:
            i += 1
        if creditors[j][1] < THRESHOLD:
            j += 1

    return transfers
