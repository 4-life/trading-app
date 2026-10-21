"""Pure unit tests, no database."""

from decimal import Decimal

from app.api.auth import TOKEN_TTL_SECONDS, issue_token, token_valid
from app.execution_engine.demo import unrealized_pnl
from app.system.app_password import hash_password, verify_hash

NOW = 1_800_000_000.0


def test_token_roundtrip() -> None:
    token = issue_token("secret", NOW)
    assert token_valid(token, "secret", NOW)


def test_token_expires() -> None:
    token = issue_token("secret", NOW)
    assert not token_valid(token, "secret", NOW + TOKEN_TTL_SECONDS + 1)


def test_token_invalid_after_password_change() -> None:
    token = issue_token("secret", NOW)
    assert not token_valid(token, "other", NOW)


def test_token_rejects_tampering_and_garbage() -> None:
    expires, _, signature = issue_token("secret", NOW).partition(".")
    assert not token_valid(f"{int(expires) + 999}.{signature}", "secret", NOW)
    assert not token_valid("garbage", "secret", NOW)
    assert not token_valid("", "secret", NOW)


def test_token_never_valid_without_password() -> None:
    assert not token_valid(issue_token("", NOW), "", NOW)


def test_unrealized_pnl_by_direction() -> None:
    entry, price, size = Decimal(100), Decimal(110), Decimal(2)
    assert unrealized_pnl("long", entry, price, size) == Decimal(20)
    assert unrealized_pnl("short", entry, price, size) == Decimal(-20)


def test_a_changed_password_is_stored_salted_and_checked_by_its_hash() -> None:
    stored = hash_password("new password")
    assert stored.startswith("scrypt$") and "new password" not in stored
    assert verify_hash("new password", stored)
    assert not verify_hash("old password", stored)
    assert hash_password("new password") != stored  # a fresh salt each time
    assert not verify_hash("new password", "plain")  # not a hash
