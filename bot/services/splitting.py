"""Splitting logic: equal and discrete (custom) splits."""
import ast
import operator
import re
from decimal import Decimal, ROUND_HALF_UP

_EXPR_WHITELIST = re.compile(r'^[\d\s\+\-\*\/\.\(\)]+$')
_MAX_EXPR_LEN = 50
_MAX_DEPTH = 10

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def _eval_node(node: ast.expr, depth: int = 0) -> float:
    if depth > _MAX_DEPTH:
        raise ValueError("Expression too deeply nested")
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (int, float)):
            raise ValueError(f"Non-numeric constant: {node.value!r}")
        return float(node.value)
    if isinstance(node, ast.BinOp):
        op_fn = _OPS.get(type(node.op))
        if op_fn is None:
            raise ValueError(f"Unsupported operator: {type(node.op).__name__}")
        left = _eval_node(node.left, depth + 1)
        right = _eval_node(node.right, depth + 1)
        if isinstance(node.op, ast.Div) and right == 0:
            raise ZeroDivisionError("Division by zero")
        return op_fn(left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -_eval_node(node.operand, depth + 1)
    raise ValueError(f"Unsupported expression node: {type(node).__name__}")


def safe_eval_expr(expr: str) -> float:
    """Safely evaluate a basic arithmetic expression (+-*/ and parens only).

    Raises ValueError for invalid/unsupported expressions, ZeroDivisionError for /0.
    """
    if len(expr) > _MAX_EXPR_LEN:
        raise ValueError(f"Expression too long (max {_MAX_EXPR_LEN} chars)")
    if not _EXPR_WHITELIST.match(expr):
        raise ValueError(f"Expression contains invalid characters: {expr!r}")
    try:
        tree = ast.parse(expr, mode='eval')
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression syntax: {expr!r}") from exc
    result = _eval_node(tree.body)
    return result


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
    """Parse '@alice 10, @bob 20' or '@alice 100/3, @bob 100/3' into splits.

    Amounts may be plain numbers or arithmetic expressions (+, -, *, /, parens).
    Spaces within the expression are allowed (e.g. '@alice 100 / 5 * 2').
    Returns (splits, errors).
    """
    splits = []
    errors = []
    seen_ids: set[int] = set()

    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        tokens = part.split()
        if len(tokens) < 2:
            errors.append(f"Cannot parse '{part}' — expected '@name amount'")
            continue

        raw_name = tokens[0]
        if not raw_name.startswith("@"):
            errors.append(f"Expected '@name' but got '{raw_name}'")
            continue

        name = raw_name.lstrip("@").lower()
        # Join remaining tokens so spaces within the expression are fine
        raw_expr = "".join(tokens[1:])

        try:
            amount = safe_eval_expr(raw_expr)
        except ZeroDivisionError:
            errors.append(f"Division by zero in expression for '@{name}'")
            continue
        except ValueError as exc:
            errors.append(f"Invalid expression '{raw_expr}' for '@{name}': {exc}")
            continue

        if amount <= 0:
            errors.append(f"Amount must be positive for '@{name}' (got {amount})")
            continue

        uid = users_by_name.get(name)
        if uid is None:
            errors.append(f"Unknown user '@{name}'")
            continue

        if uid in seen_ids:
            errors.append(f"Duplicate entry for '@{name}'")
            continue

        seen_ids.add(uid)
        splits.append((uid, round(amount, 2)))

    return splits, errors
