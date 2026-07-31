"""Hardware abstraction for Sequent Microsystems 8-relay HAT.

Supports a pure in-memory MockRelayBoard (for development) and the real
lib8relind driver when running on a Raspberry Pi with the hat installed.
"""

from __future__ import annotations

from typing import Protocol

from loguru import logger as log


class RelayBoard(Protocol):
    def set(self, relay: int, value: int) -> None: ...
    def get(self, relay: int) -> int: ...
    def set_all(self, value: int) -> None: ...
    def get_all(self) -> int: ...
    def close(self) -> None: ...


class MockRelayBoard:
    """In-memory 8-relay simulator. State is a simple bitmask."""

    def __init__(self, stack: int = 0) -> None:
        self.stack = stack
        self._state = 0  # bit 0 = relay 1, bit 7 = relay 8
        log.info(f"MockRelayBoard (stack={stack}) ready")

    def set(self, relay: int, value: int) -> None:
        if not 1 <= relay <= 8:
            raise ValueError(f"relay must be 1..8, got {relay}")
        bit = 1 << (relay - 1)
        if value:
            self._state |= bit
        else:
            self._state &= ~bit
        log.debug(f"Mock set relay {relay} → {value}  (mask=0b{self._state:08b})")

    def get(self, relay: int) -> int:
        if not 1 <= relay <= 8:
            raise ValueError(f"relay must be 1..8, got {relay}")
        return 1 if (self._state & (1 << (relay - 1))) else 0

    def set_all(self, value: int) -> None:
        self._state = value & 0xFF
        log.debug(f"Mock set_all → 0b{self._state:08b}")

    def get_all(self) -> int:
        return self._state

    def close(self) -> None:
        self._state = 0
        log.info("MockRelayBoard closed (all off)")


class RealRelayBoard:
    """Thin wrapper around Sequent Microsystems lib8relind."""

    def __init__(self, stack: int = 0) -> None:
        try:
            import lib8relind  # type: ignore
        except ImportError as e:
            raise RuntimeError("lib8relind not installed.") from e
        self._lib = lib8relind
        self.stack = stack
        # quick presence check
        try:
            self._lib.get_all(stack)
        except Exception as e:
            raise RuntimeError(
                f"Failed to talk to 8-relay hat (stack={stack}): {e}"
            ) from e
        log.info(f"RealRelayBoard (stack={stack}) ready")

    def set(self, relay: int, value: int) -> None:
        self._lib.set(self.stack, relay, 1 if value else 0)

    def get(self, relay: int) -> int:
        return self._lib.get(self.stack, relay)

    def set_all(self, value: int) -> None:
        self._lib.set_all(self.stack, value & 0xFF)

    def get_all(self) -> int:
        return self._lib.get_all(self.stack)

    def close(self) -> None:
        self.set_all(0)
        log.info("RealRelayBoard closed (all off)")


def create_board(mock: bool, stack: int = 0) -> RelayBoard:
    if mock:
        return MockRelayBoard(stack=stack)
    return RealRelayBoard(stack=stack)
