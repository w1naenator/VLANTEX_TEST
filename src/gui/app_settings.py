from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
import json
import sys


SETTINGS_FILENAME = "settings.json"


@dataclass
class AppSettings:
    address: str = "192.168.61.110"
    rack: int = 0
    slot: int = 1
    tcp_port: int = 102
    db: int = 200
    start: int = 0
    size: int = 22440
    interval_ms: int = 1000


def get_settings_path() -> Path:
    base = Path(sys.argv[0]).resolve().parent
    return base / SETTINGS_FILENAME



def load_settings() -> AppSettings:
    path = get_settings_path()
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}

    return AppSettings(
        address=str(data.get("address", AppSettings.address)),
        rack=int(data.get("rack", AppSettings.rack)),
        slot=int(data.get("slot", AppSettings.slot)),
        tcp_port=int(data.get("tcp_port", AppSettings.tcp_port)),
        db=int(data.get("db", AppSettings.db)),
        start=int(data.get("start", AppSettings.start)),
        size=int(data.get("size", AppSettings.size)),
        interval_ms=int(data.get("interval_ms", AppSettings.interval_ms)),
    )


def save_settings(settings: AppSettings) -> None:
    path = get_settings_path()
    try:
        with path.open("w", encoding="utf-8") as f:
            json.dump(asdict(settings), f, indent=2)
    except Exception:
        # best-effort; caller may log to console
        pass
