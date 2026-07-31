import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from loguru import logger as log


def _resolve_config_path(name="config.toml") -> Path:
    return Path(__file__).parent.parent / "config" / name


def _resolve_data_ingest_path(name="inbound") -> Path:
    return Path(__file__).parent.parent / "ingest" / name


@dataclass
class Zone:
    index: int
    relay_num: int
    display_name: str = ""
    enabled: bool = True
    location: str | None = None


@dataclass
class Safety:
    max_run_time_s: int = 1800
    watchdog_interval_s: int = 30
    watchdog_pin: int | None = None
    watchdog_relay: int | None = None


@dataclass
class WebAppConfig:
    enabled: bool = True
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class TelemetryConfig:
    watch_dir: str | Path = field(default_factory=lambda: _resolve_data_ingest_path())
    config_path: str | Path = field(
        default_factory=lambda: _resolve_config_path("data_config.toml")
    )


@dataclass
class AppConfig:
    mock: bool = False
    stack: int = 0
    debounce: int = 5
    settling_time: float = 0.05
    log_level: str = "INFO"


@dataclass
class Config:
    app: AppConfig = field(default_factory=AppConfig)
    safety: Safety = field(default_factory=Safety)
    web_app: WebAppConfig = field(default_factory=WebAppConfig)
    zones: list[Zone] = field(default_factory=list)
    telemetry: TelemetryConfig = field(default_factory=TelemetryConfig)

    def enabled_zones(self) -> list[Zone]:
        return [z for z in self.zones if z.enabled]

    def zone_by_index(self, index: int) -> Zone | None:
        return next((z for z in self.zones if z.index == index), None)

    @classmethod
    def load(cls, path: Path | str | None = None) -> Config:

        if path is None:
            path = _resolve_config_path()

        path = Path(path)

        if not path.exists():
            log.warning(f"Config file not found: {path} -- using defaults")
            return cls()

        raw = tomllib.loads(path.read_text())
        app = AppConfig(**raw.get("app", {}))
        safety = Safety(**raw.get("safety", {}))
        web_app = WebAppConfig(**raw.get("web_app", {}))
        telemetry = TelemetryConfig(**raw.get("telemetry", {}))
        zones = [Zone(**v) for v in raw.get("zones", [])]

        return cls(
            app=app,
            safety=safety,
            web_app=web_app,
            zones=zones,
            telemetry=telemetry,
        )
