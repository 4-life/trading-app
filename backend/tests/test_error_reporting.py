"""Pure unit tests, no database or network."""

import logging
import sys

from app.notifications.alerts import redact
from app.notifications.error_reporting import REPEAT_SECONDS, ErrorForwarder, format_error


def _record(msg: str, exc: Exception | None = None, name: str = "app.x") -> logging.LogRecord:
    exc_info = None
    if exc is not None:
        try:
            raise exc
        except type(exc):
            exc_info = sys.exc_info()
    return logging.LogRecord(name, logging.ERROR, __file__, 1, msg, None, exc_info)


def test_same_error_is_sent_once_per_window_then_reports_the_suppressed_count() -> None:
    forwarder = ErrorForwarder("svc")
    record = _record("poll failed", ValueError("boom"))
    assert forwarder.should_send(record, 0.0) == (True, 0)
    assert forwarder.should_send(record, 10.0) == (False, 0)
    assert forwarder.should_send(record, 20.0) == (False, 0)
    assert forwarder.should_send(record, REPEAT_SECONDS + 1) == (True, 2)


def test_different_errors_are_sent_independently() -> None:
    forwarder = ErrorForwarder("svc")
    assert forwarder.should_send(_record("a failed", ValueError()), 0.0)[0]
    assert forwarder.should_send(_record("a failed", KeyError()), 1.0)[0]
    assert forwarder.should_send(_record("b failed", ValueError()), 2.0)[0]


def test_message_has_the_error_and_the_suppressed_count_but_no_traceback() -> None:
    try:
        raise RuntimeError("no route\nsecond line")
    except RuntimeError as exc:
        record = _record("poll %s failed", exc)
        record.exc_info = (RuntimeError, exc, exc.__traceback__)
    text = format_error(record, suppressed=3)
    assert "RuntimeError: no route" in text and "second line" not in text
    assert "Traceback" not in text and 'File "' not in text
    assert "+3 more like this" in text


def test_url_query_strings_are_redacted() -> None:
    exc = RuntimeError(
        "Client error '405' for url 'https://mainnet.zklighter.elliot.ai/api/v1/account?by=index&value=123456'"
    )
    text = format_error(_record("poll failed", exc), suppressed=0)
    assert "123456" not in text and "/api/v1/account?…" in text


def test_keys_and_tokens_are_redacted_the_rest_kept() -> None:
    key = "0x" + "ab12" * 16
    bot = "123456789:AAH" + "x" * 32
    text = redact(f"sign failed for {key} via bot{bot}; Bearer 1800000000.abc")
    assert key not in text and bot not in text and "1800000000.abc" not in text
    assert text.startswith("sign failed for [redacted]")
    plain = "paper 12: BTC 1h rejected - HTTP 429, retry in 5 s (price 84512.30)"
    assert redact(plain) == plain
    assert redact("GET https://api.x/info?user=0x12 failed") == "GET https://api.x/info?… failed"
