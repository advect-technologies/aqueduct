"""Stateful async irrigation controller.

Enforces the hard rule: at most one valve may be energized at any time.
All public methods are async and protected by a single lock.
"""

import asyncio
import time

from loguru import logger as log

from . import models
from .config import Config, Zone
from .hardware import RelayBoard, create_board


class StateManager:
    def __init__(self):
        self.entered_time: float = time.monotonic()
        self._current_state: models.States = models.States.INIT

    @property
    def current_state(self) -> models.States:
        return self._current_state

    @current_state.setter
    def current_state(self, state: models.States):
        if not isinstance(state, models.States):
            raise TypeError(f"Invalid state: {state}")

        self.entered_time = time.monotonic()
        self._current_state = state

    @property
    def total_time(self) -> float:
        return time.monotonic() - self.entered_time


class IrrigationController:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.board: RelayBoard = create_board(config.app.mock, stack=config.app.stack)
        self._lock = asyncio.Lock()
        self._opened_at: dict[int, float] = {}  # zone → monotonic time
        self._start_time = time.monotonic()

        self._event_q = asyncio.Queue()
        self.state_manager = StateManager()
        self._current_zone: Zone | None = None
        self._state_timeout_reset: asyncio.Event = asyncio.Event()

        # Ensure everything starts off
        self.board.set_all(0)
        log.info(
            f"IrrigationController started  mock={config.app.mock}  "
            f"valves={len(config.zones)}  stack={config.app.stack}"
        )

    @property
    def current_zone(self) -> Zone | None:
        return self._current_zone

    async def set_current_zone(self, zone: Zone | None) -> None:
        async with self._lock:
            await self._close_current_valve()
            self._current_zone = zone

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _event_handler(self, event: models.Events) -> None:
        match event:
            case models.OpenValveEvent():
                if self.state_manager.current_state == models.States.FAULT:
                    log.debug("OpenValveEvent ignored in FAULT state")
                    return
                if self.state_manager.total_time < self.config.app.debounce:
                    log.debug("OpenValveEvent ignored before debounce time")
                    return
                if self.config.zone_by_index(event.zone_index) is None:
                    log.debug("OpenValveEvent ignored for invalid zone index")
                    return
                await self.set_current_zone(self.config.zone_by_index(event.zone_index))
                await self._transition_state(models.States.ACTIVE)
            case models.CloseValveEvent():
                await self._transition_state(models.States.IDLE)
            case models.ShutdownEvent():
                await self._transition_state(models.States.IDLE)
            case models.FaultEvent():
                await self._transition_state(models.States.FAULT)
            case _:
                pass

    async def _transition_state(self, new_state: models.States) -> None:
        match new_state:
            case models.States.IDLE:
                await self.set_current_zone(None)
            case models.States.ACTIVE:
                await self._open_current_valve()
            case models.States.FAULT:
                await self.set_current_zone(None)
                await self._close_all_valves()
                # TODO: add hard circuit disconnect to cut all power from valves
            case models.States.INIT:
                pass
            case _:
                return
        self._state_timeout_reset.set()
        self.state_manager.current_state = new_state

    async def _close_current_valve(self) -> None:
        if self.current_zone is not None:
            self.board.set(self.current_zone.relay_num, 0)
            await asyncio.sleep(self.config.app.settling_time)

    async def _close_all_valves(self) -> None:
        async with self._lock:
            for valve in self.config.zones:
                self.board.set(valve.relay_num, 0)
                await asyncio.sleep(self.config.app.settling_time)

    async def _open_current_valve(self) -> None:
        if self.current_zone is not None:
            self.board.set(self.current_zone.relay_num, 1)
            await asyncio.sleep(self.config.app.settling_time)

    # ------------------------------------------------------------------
    # External
    # ------------------------------------------------------------------
    def submit(self, event: models.Events) -> None:
        self._event_q.put_nowait(event)

    def get_status(self) -> models.ControllerStatus:
        zones = tuple(
            models.ZoneStatus(
                index=z.index,
                display_name=z.display_name or f"Zone {z.index}",
                relay_num=z.relay_num,
                enabled=z.enabled,
                location=z.location,
                is_open=bool(self.board.get(z.relay_num)),
            )
            for z in self.config.zones
        )
        active = self._current_zone.index if self._current_zone is not None else None
        return models.ControllerStatus(
            state=self.state_manager.current_state,
            state_age_s=round(self.state_manager.total_time, 1),
            active_zone_index=active,
            uptime_s=round(time.monotonic() - self._start_time, 1),
            zones=zones,
        )

    async def shutdown(self) -> None:
        self.submit(models.ShutdownEvent())
        # brief window for the event task to process the close
        await asyncio.sleep(self.config.app.settling_time + 0.05)
        self.board.close()
        log.info("Controller shutdown complete")

    # ------------------------------------------------------------------
    # Tasks
    # ------------------------------------------------------------------

    async def _event_task(self) -> None:
        while True:
            try:
                event = await self._event_q.get()
                await self._event_handler(event)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                log.error(f"Error in event task: {e}")

    async def timeout_task(self) -> None:
        while True:
            try:
                if self.state_manager.current_state == models.States.ACTIVE:
                    async with asyncio.timeout(self.config.safety.max_run_time_s):
                        await self._state_timeout_reset.wait()
                else:
                    await self._state_timeout_reset.wait()
                self._state_timeout_reset.clear()
            except TimeoutError:
                self._state_timeout_reset.clear()
                await self._event_q.put(models.FaultEvent(models.Faults.TIMEOUT))

    async def run(self) -> None:
        await self._transition_state(models.States.IDLE)
        try:
            async with asyncio.TaskGroup() as tg:
                tg.create_task(self._event_task())
                tg.create_task(self.timeout_task())
        finally:
            try:
                self.board.set_all(0)
                self._current_zone = None
            except Exception as e:
                log.error(f"Failed to force relays off on run exit: {e}")
            log.info("Controller run exited — all relays forced off")
