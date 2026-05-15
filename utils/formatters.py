from decimal import Decimal, InvalidOperation


def parse_decimal(value, field_name="value", default="0") -> Decimal:
    raw = (value or "").strip()
    if not raw:
        return Decimal(default)
    try:
        return Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f'Invalid {field_name}: "{raw}"') from exc


def parse_coordinate(value, minimum, maximum):
    raw = str(value or "").strip()
    if not raw:
        return None

    try:
        parsed = float(raw)
    except (TypeError, ValueError):
        return None

    if parsed < minimum or parsed > maximum:
        return None
    return round(parsed, 7)
