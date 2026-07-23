from __future__ import annotations

import base64
import hashlib
from decimal import Decimal, InvalidOperation
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from flask import current_app
from sqlalchemy.types import LargeBinary, TypeDecorator


class FinancialEncryptionError(RuntimeError):
    pass


def _normalize_key(raw_key: str) -> bytes:
    value = (raw_key or "").strip()
    if not value:
        raise FinancialEncryptionError(
            "FINANCIAL_DATA_ENCRYPTION_KEY is not configured. "
            "Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        return value.encode("utf-8")
    except Exception as exc:
        raise FinancialEncryptionError("Invalid FINANCIAL_DATA_ENCRYPTION_KEY encoding.") from exc


def get_financial_fernet() -> Fernet:
    key = current_app.config.get("FINANCIAL_DATA_ENCRYPTION_KEY")
    if not key and current_app.config.get("ENV") == "testing":
        key = current_app.config.get("FINANCIAL_DATA_ENCRYPTION_KEY_TEST_FALLBACK")
    if not key and current_app.config.get("ALLOW_DEV_FINANCIAL_KEY_DERIVATION"):
        secret = (current_app.config.get("SECRET_KEY") or "").encode("utf-8")
        derived = hashlib.sha256(b"sweetcrumbs-finance:" + secret).digest()
        key = base64.urlsafe_b64encode(derived).decode("utf-8")
    return Fernet(_normalize_key(key))


def encrypt_text(value: Optional[str]) -> Optional[bytes]:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return get_financial_fernet().encrypt(text.encode("utf-8"))


def decrypt_text(value: Optional[bytes]) -> Optional[str]:
    if value is None:
        return None
    try:
        return get_financial_fernet().decrypt(value).decode("utf-8")
    except InvalidToken as exc:
        raise FinancialEncryptionError("Unable to decrypt financial field.") from exc


def encrypt_decimal(value: Optional[Decimal]) -> Optional[bytes]:
    if value is None:
        return None
    return encrypt_text(format(Decimal(str(value)), "f"))


def decrypt_decimal(value: Optional[bytes]) -> Optional[Decimal]:
    text = decrypt_text(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise FinancialEncryptionError("Unable to decode encrypted decimal.") from exc


class EncryptedText(TypeDecorator):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return None
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        return encrypt_text(str(value))

    def process_result_value(self, value, dialect):
        return decrypt_text(value)


class EncryptedDecimal(TypeDecorator):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None or value == "":
            return None
        if isinstance(value, (bytes, bytearray)):
            return bytes(value)
        return encrypt_decimal(Decimal(str(value)))

    def process_result_value(self, value, dialect):
        return decrypt_decimal(value)
