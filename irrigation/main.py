"""Entry point for the irrigation controller."""

from __future__ import annotations

import asyncio
import signal
import sys

from loguru import logger as log

from .config import Config
from .controller import IrrigationController
from .web import start_web


def _setup_logging(level: str = "INFO") -> None:
    log.remove()
    log.add(
        sys.stderr,
        level=level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}",
    )


async def run(config_path: str | None = None) -> None:
    config = Config.load(config_path)
    _setup_logging(config.app.log_level)
    log.info(
        f"Loaded config  mock={config.app.mock}  "
        f"zones={len(config.zones)}  stack={config.app.stack}"
    )

    controller = IrrigationController(config)
    runner = None
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        log.info("Shutdown signal received")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass

    # Start the controller's internal tasks (event consumer + timeout watchdog)
    controller_task = asyncio.create_task(controller.run(), name="controller")

    try:
        if config.web_app.enabled:
            runner = await start_web(
                controller,
                host=config.web_app.host,
                port=config.web_app.port,
            )

        log.info("Controller running — Ctrl+C to stop")
        await stop_event.wait()

    finally:
        if runner is not None:
            await runner.cleanup()
        await controller.shutdown()
        controller_task.cancel()
        try:
            await controller_task
        except asyncio.CancelledError:
            pass
        log.info("Bye")


def main() -> None:
    config_path = sys.argv[1] if len(sys.argv) > 1 else None
    try:
        asyncio.run(run(config_path))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
