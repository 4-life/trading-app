"""Server errors -> Telegram (docs/watchdog.md#alerting).

Every service logs through `setup_logging`, which adds ErrorForwarder: any
record at ERROR or above (e.g. `logger.exception(...)` in a poll loop) is
sent as an alert. The same error from the same place is sent at most once
per REPEAT_SECONDS; the next one after that says how many were suppressed.
`run_service` also reports a service that crashes outright.

Telegram is a third party: an alert carries only the message and the
exception's type and text - no traceback (code, file paths), and URLs lose
their query strings (account ids and the like). The full traceback stays in
the service's log on the server."""

import asyncio
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from app.notifications.alerts import alert, redact

REPEAT_SECONDS = 15 * 60
MAX_DETAIL_CHARS = 300
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

logger = logging.getLogger(__name__)


def error_key(record: logging.LogRecord) -> tuple[str, str, str]:
    """Same place + same message template + same exception type = same error."""
    exc_type = record.exc_info[0].__name__ if record.exc_info and record.exc_info[0] else ""
    return record.name, str(record.msg), exc_type


def describe(exc: BaseException) -> str:
    """The exception's type and first line - safe to send, no traceback."""
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else ""
    detail = redact(detail)[:MAX_DETAIL_CHARS]
    return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__


def format_error(record: logging.LogRecord, suppressed: int) -> str:
    text = redact(record.getMessage())
    if record.exc_info and record.exc_info[1] is not None:
        text += f" - {describe(record.exc_info[1])}"
    if suppressed:
        text += f"\n(+{suppressed} more like this in the last {REPEAT_SECONDS // 60} min)"
    return text


class ErrorForwarder(logging.Handler):
    def __init__(self, service: str) -> None:
        super().__init__(level=logging.ERROR)
        self.service = service
        self.loop: asyncio.AbstractEventLoop | None = None
        # key -> (last sent at, suppressed since)
        self._sent: dict[tuple[str, str, str], tuple[float, int]] = {}

    def should_send(self, record: logging.LogRecord, now: float) -> tuple[bool, int]:
        """(send it?, how many were suppressed before it)."""
        key = error_key(record)
        if key not in self._sent:
            self._sent[key] = (now, 0)
            return True, 0
        last, suppressed = self._sent[key]
        if now - last < REPEAT_SECONDS:
            self._sent[key] = (last, suppressed + 1)
            return False, 0
        self._sent[key] = (now, 0)
        return True, suppressed

    def emit(self, record: logging.LogRecord) -> None:
        # Never forward the notification code's own errors - that would loop.
        if record.name.startswith("app.notifications"):
            return
        loop: asyncio.AbstractEventLoop | None
        try:
            loop = asyncio.get_running_loop()
            self.loop = loop
        except RuntimeError:  # logged from a worker thread
            loop = self.loop
        if loop is None or loop.is_closed():
            return
        send, suppressed = self.should_send(record, time.monotonic())
        if send:
            message = format_error(record, suppressed)
            asyncio.run_coroutine_threadsafe(alert(self.service, "error", message), loop)


def setup_logging(service: str) -> None:
    """Timestamped logs to stdout, errors forwarded to Telegram."""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    root = logging.getLogger()
    if not any(isinstance(h, ErrorForwarder) for h in root.handlers):
        root.addHandler(ErrorForwarder(service))


def run_service(service: str, main: Callable[[], Coroutine[Any, Any, None]]) -> None:
    """Entrypoint for a service: logging + error forwarding, and a Telegram
    alert if the service crashes (Docker then restarts it)."""
    setup_logging(service)
    try:
        asyncio.run(main())
    except Exception as exc:
        logger.exception("%s crashed", service)
        asyncio.run(alert(service, "critical", f"service crashed - restarting: {describe(exc)}"))
        raise
