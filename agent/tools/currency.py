"""Currency helpers — Indian Rupee (INR) formatting."""

CURRENCY = "INR"
SYMBOL = "₹"


def _group_indian(digits: str) -> str:
    """Group an integer digit string Indian-style: last 3, then pairs (1,29,999)."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join(parts + [tail])


def format_inr(value, decimals: int = 0, default: str = "N/A") -> str:
    """Format a number as ₹ with Indian digit grouping, e.g. 129999 -> '₹1,29,999'."""
    try:
        num = float(value)
    except (TypeError, ValueError):
        return default
    sign = "-" if num < 0 else ""
    num = abs(num)
    text = f"{num:.{decimals}f}"
    whole, _, frac = text.partition(".")
    out = _group_indian(whole)
    if frac:
        out += "." + frac
    return f"{sign}{SYMBOL}{out}"
