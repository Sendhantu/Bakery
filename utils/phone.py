"""Phone-number normalization helpers used for account matching and fraud
prevention. Only normalized, reversible-free forms are compared so that
walk-in / registration inputs such as ``9876543210``, ``09876543210`` and
``+91 98765 43210`` all resolve to the same customer.
"""
import re

_DIGITS_RE = re.compile(r"\D+")


def digits_only(value):
    if value is None:
        return ""
    return _DIGITS_RE.sub("", str(value))


def normalize_mobile(value, country_code="IN"):
    """Return an E.164-style normalized mobile (``+91XXXXXXXXXX``) or None.

    Accepts local and international spellings for the store country. Returns
    None when the value is empty or does not look like a valid mobile number.
    """
    digits = digits_only(value)
    if not digits:
        return None
    country_code = (country_code or "IN").strip().upper()
    if country_code == "IN":
        if len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        if len(digits) != 10:
            return None
        return f"+91{digits}"
    if digits.startswith(country_code):
        digits = digits[len(country_code):]
    if not digits:
        return None
    return f"+{digits}"


def mobile_last_10(value):
    """Return the trailing 10 digits of a stored phone value, or None."""
    digits = digits_only(value)
    if len(digits) < 10:
        return None
    return digits[-10:]
