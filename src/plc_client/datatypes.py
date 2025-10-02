"""Data type helpers for Siemens PLC payloads."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import struct
from typing import ClassVar, Iterable, Tuple


@dataclass(frozen=True)
class DTL:
    """Represents the Siemens S7 DTL (Date and Time) structure."""

    year: int
    month: int
    day: int
    weekday: int
    hour: int
    minute: int
    second: int
    nanosecond: int

    _STRUCT: ClassVar[struct.Struct] = struct.Struct(">H6BI")

    def to_bytes(self) -> bytes:
        """Serialize the DTL structure to its 12-byte representation."""

        return self._STRUCT.pack(
            self.year,
            self.month,
            self.day,
            self.weekday,
            self.hour,
            self.minute,
            self.second,
            self.nanosecond,
        )

    @classmethod
    def from_bytes(cls, payload: bytes) -> "DTL":
        """Create a DTL instance from a 12-byte payload."""

        if len(payload) != cls._STRUCT.size:
            raise ValueError(
                f"DTL payload must be {cls._STRUCT.size} bytes, got {len(payload)}"
            )
        year, month, day, weekday, hour, minute, second, nanosecond = cls._STRUCT.unpack(
            payload
        )
        return cls(year, month, day, weekday, hour, minute, second, nanosecond)

    def to_datetime(self) -> datetime:
        """Convert to a Python datetime (nanoseconds truncated to microseconds)."""

        microseconds = self.nanosecond // 1000
        return datetime(
            year=self.year,
            month=self.month,
            day=self.day,
            hour=self.hour,
            minute=self.minute,
            second=self.second,
            microsecond=microseconds,
        )


@dataclass(frozen=True)
class SAWLOG:
    """Represents the SAWLOG structure with packed flags and nibble data."""

    id: int
    zone_id: int
    sensor_id: int
    length: int
    drop_box_number: int
    flags: Tuple[bool, ...]
    buttons: Tuple[int, ...]
    timestamp: DTL

    FLAGS_COUNT: ClassVar[int] = 16
    BUTTON_COUNT: ClassVar[int] = 64
    _HEADER_STRUCT: ClassVar[struct.Struct] = struct.Struct(">IBBHH")
    _FLAGS_BYTE_SIZE: ClassVar[int] = 2
    _BUTTONS_BYTE_SIZE: ClassVar[int] = BUTTON_COUNT // 2
    BYTE_SIZE: ClassVar[int] = (
        _HEADER_STRUCT.size
        + _FLAGS_BYTE_SIZE
        + _BUTTONS_BYTE_SIZE
        + DTL._STRUCT.size
    )

    def __post_init__(self) -> None:
        flags = tuple(bool(flag) for flag in self.flags)
        if len(flags) != self.FLAGS_COUNT:
            raise ValueError(f"flags must contain {self.FLAGS_COUNT} entries")
        object.__setattr__(self, "flags", flags)

        buttons = tuple(int(button) for button in self.buttons)
        if len(buttons) != self.BUTTON_COUNT:
            raise ValueError(f"buttons must contain {self.BUTTON_COUNT} entries")
        if any(button < 0 or button > 0x0F for button in buttons):
            raise ValueError("buttons must be in range 0-15")
        object.__setattr__(self, "buttons", buttons)

        if self.id < 0:
            raise ValueError("id must be non-negative")
        if not (0 <= self.zone_id <= 0xFF):
            raise ValueError("zone_id must fit in an unsigned byte")
        if not (0 <= self.sensor_id <= 0xFF):
            raise ValueError("sensor_id must fit in an unsigned byte")
        if not (0 <= self.length <= 0xFFFF):
            raise ValueError("length must fit in an unsigned word")
        if not (0 <= self.drop_box_number <= 0xFFFF):
            raise ValueError("drop_box_number must fit in an unsigned word")

    def to_bytes(self) -> bytes:
        """Serialize the structure into the packed PLC representation."""

        header = self._HEADER_STRUCT.pack(
            self.id,
            self.zone_id,
            self.sensor_id,
            self.length,
            self.drop_box_number,
        )
        flags_bytes = self._pack_flags(self.flags)
        buttons_bytes = self._pack_buttons(self.buttons)
        return header + flags_bytes + buttons_bytes + self.timestamp.to_bytes()

    @classmethod
    def from_bytes(cls, payload: bytes) -> "SAWLOG":
        """Parse the SAWLOG structure from its packed PLC representation."""

        if len(payload) != cls.BYTE_SIZE:
            raise ValueError(f"SAWLOG payload must be {cls.BYTE_SIZE} bytes, got {len(payload)}")

        offset = 0
        header = cls._HEADER_STRUCT.unpack_from(payload, offset)
        offset += cls._HEADER_STRUCT.size

        flags_bytes = payload[offset : offset + cls._FLAGS_BYTE_SIZE]
        offset += cls._FLAGS_BYTE_SIZE

        buttons_bytes = payload[offset : offset + cls._BUTTONS_BYTE_SIZE]
        offset += cls._BUTTONS_BYTE_SIZE

        timestamp_bytes = payload[offset : offset + DTL._STRUCT.size]

        flags = cls._unpack_flags(flags_bytes)
        buttons = cls._unpack_buttons(buttons_bytes)
        timestamp = DTL.from_bytes(timestamp_bytes)

        return cls(
            id=header[0],
            zone_id=header[1],
            sensor_id=header[2],
            length=header[3],
            drop_box_number=header[4],
            flags=flags,
            buttons=buttons,
            timestamp=timestamp,
        )

    @classmethod
    def from_iterable(cls, payloads: Iterable[bytes]) -> Tuple["SAWLOG", ...]:
        """Create SAWLOG instances from an iterable of raw payloads."""

        return tuple(cls.from_bytes(payload) for payload in payloads)

    @classmethod
    def array_from_bytes(cls, payload: bytes) -> Tuple["SAWLOG", ...]:
        """Convert a raw byte buffer into SAWLOG records."""

        if len(payload) % cls.BYTE_SIZE != 0:
            raise ValueError(
                f"Payload length {len(payload)} is not a multiple of SAWLOG size {cls.BYTE_SIZE}"
            )
        records = []
        view = memoryview(payload)
        for offset in range(0, len(payload), cls.BYTE_SIZE):
            chunk = view[offset : offset + cls.BYTE_SIZE]
            records.append(cls.from_bytes(bytes(chunk)))
        return tuple(records)

    @staticmethod
    def _pack_flags(flags: Tuple[bool, ...]) -> bytes:
        value = 0
        for index, flag in enumerate(flags):
            if flag:
                value |= 1 << index
        return value.to_bytes(SAWLOG._FLAGS_BYTE_SIZE, byteorder="big")

    @staticmethod
    def _unpack_flags(payload: bytes) -> Tuple[bool, ...]:
        if len(payload) != SAWLOG._FLAGS_BYTE_SIZE:
            raise ValueError("flags payload has invalid length")
        value = int.from_bytes(payload, byteorder="big")
        return tuple(bool(value & (1 << index)) for index in range(SAWLOG.FLAGS_COUNT))

    @staticmethod
    def _pack_buttons(buttons: Tuple[int, ...]) -> bytes:
        buffer = bytearray(SAWLOG._BUTTONS_BYTE_SIZE)
        for i in range(0, SAWLOG.BUTTON_COUNT, 2):
            high = buttons[i] & 0x0F
            low = buttons[i + 1] & 0x0F
            buffer[i // 2] = (high << 4) | low
        return bytes(buffer)

    @staticmethod
    def _unpack_buttons(payload: bytes) -> Tuple[int, ...]:
        if len(payload) != SAWLOG._BUTTONS_BYTE_SIZE:
            raise ValueError("buttons payload has invalid length")
        result = []
        for byte in payload:
            result.append(byte >> 4)
            result.append(byte & 0x0F)
        return tuple(result)


@dataclass(frozen=True)
class SawlogsRegisterDB:
    """Represents the full SAWLOG register data block (255 records)."""

    records: Tuple[SAWLOG, ...]

    CAPACITY: ClassVar[int] = 255
    DB_BYTE_SIZE: ClassVar[int] = CAPACITY * SAWLOG.BYTE_SIZE

    def __post_init__(self) -> None:
        normalized = tuple(self.records)
        if len(normalized) != self.CAPACITY:
            raise ValueError(f"records must contain exactly {self.CAPACITY} SAWLOG entries")
        object.__setattr__(self, "records", normalized)

    def __iter__(self):  # type: ignore[override]
        return iter(self.records)

    def to_bytes(self) -> bytes:
        """Serialize the entire register array to bytes."""

        return b"".join(record.to_bytes() for record in self.records)

    @classmethod
    def from_bytes(cls, payload: bytes) -> "SawlogsRegisterDB":
        """Create a register array from raw bytes."""

        if len(payload) != cls.DB_BYTE_SIZE:
            raise ValueError(
                f"Payload must be {cls.DB_BYTE_SIZE} bytes for {cls.CAPACITY} SAWLOG entries; got {len(payload)}"
            )
        records = SAWLOG.array_from_bytes(payload)
        if len(records) != cls.CAPACITY:
            raise ValueError(
                f"Expected {cls.CAPACITY} SAWLOG entries, parsed {len(records)}"
            )
        return cls(records)
