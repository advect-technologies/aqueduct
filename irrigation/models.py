import time
from dataclasses import dataclass
from enum import StrEnum, auto


class States(StrEnum):
    IDLE = auto()
    ACTIVE = auto()
    FAULT = auto()
    INIT = auto()


class Faults(StrEnum):
    UNKNOWN = auto()
    TIMEOUT = auto()


@dataclass(frozen=True)
class ZoneStatus:
    index: int
    display_name: str
    relay_num: int
    enabled: bool
    location: str | None
    is_open: bool


@dataclass(frozen=True)
class ControllerStatus:
    state: States
    state_age_s: float
    active_zone_index: int | None
    uptime_s: float
    zones: tuple[ZoneStatus, ...]


class Event:
    def __init__(self) -> None:
        self.timestamp = time.monotonic()


class OpenValveEvent(Event):
    def __init__(self, zone_index: int) -> None:
        super().__init__()
        self.zone_index = zone_index


class CloseValveEvent(Event):
    def __init__(self) -> None:
        super().__init__()


class ShutdownEvent(Event):
    def __init__(self) -> None:
        super().__init__()


class FaultEvent(Event):
    def __init__(self, code: Faults = Faults.UNKNOWN) -> None:
        super().__init__()
        self.message = code


Events = OpenValveEvent | CloseValveEvent | ShutdownEvent | FaultEvent
