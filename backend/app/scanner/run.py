import asyncio

from app.exchange.source import connected_adapter, exit_on_source_change
from app.notifications.error_reporting import run_service
from app.scanner.service import SERVICE, Scanner

POLL_SECONDS = 30


async def _scan(scanner: Scanner) -> None:
    while True:
        await scanner.run_once()
        await asyncio.sleep(POLL_SECONDS)


async def main() -> None:
    source, adapter = await connected_adapter()
    await asyncio.gather(_scan(Scanner(adapter)), exit_on_source_change(source))


if __name__ == "__main__":
    run_service(SERVICE, main)
