"""Configuration objects for S7-200SP PLC connections."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class PLCConfig:
    """Connection parameters for a Siemens S7 PLC."""

    address: str
    rack: int = 0
    slot: int = 1
    tcp_port: int = 102

    def __post_init__(self) -> None:
        if not self.address:
            raise ValueError("address must be a non-empty IP address or hostname")
        if self.rack < 0:
            raise ValueError("rack must be non-negative")
        if self.slot < 0:
            raise ValueError("slot must be non-negative")
        if not (0 < self.tcp_port < 65536):
            raise ValueError("tcp_port must be in range 1-65535")

    def as_kwargs(self) -> Dict[str, object]:
        """Return keyword arguments suitable for the PLC client."""

        return {
            "address": self.address,
            "rack": self.rack,
            "slot": self.slot,
            "tcp_port": self.tcp_port,
        }
