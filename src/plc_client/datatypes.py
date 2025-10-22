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
    """Represents the SAWLOG structure.

    New layout (big-endian):
    - id: U32
    - zone_id: U8
    - sensor_id: U8
    - length: U16
    - position: U32
    - drop_box_number: U16
    - flags_0: 16 boolean flags packed into 2 bytes (bit0 = FL0)
    - flags_1: 16 boolean flags packed into 2 bytes (bit0 = FL16)
    - buttons: Byte[2][32] => 64 bytes total, first 32 then second 32
               (kept here as a flat tuple of 64 bytes: orders[32] + counts[32])
    - timestamp: DTL (12 bytes)
    """

    id: int
    zone_id: int
    sensor_id: int
    length: int
    position: int
    drop_box_number: int
    # 32 flags total, flattened FL0..FL31
    flags: Tuple[bool, ...]
    # buttons stored as 64 raw bytes: first 32, then 32 (e.g. orders[32] + counts[32])
    buttons: Tuple[int, ...]
    timestamp: DTL

    FLAGS_COUNT: ClassVar[int] = 32
    BUTTON_COUNT: ClassVar[int] = 32
    _HEADER_STRUCT: ClassVar[struct.Struct] = struct.Struct(">IBBHIH")
    _FLAGS_BYTE_SIZE: ClassVar[int] = 4  # two groups of 16
    _BUTTONS_BYTE_SIZE: ClassVar[int] = BUTTON_COUNT * 2  # 64 bytes
    BYTE_SIZE: ClassVar[int] = (
        _HEADER_STRUCT.size
        + _FLAGS_BYTE_SIZE
        + _BUTTONS_BYTE_SIZE
        + DTL._STRUCT.size
    )
    # Legacy (v1) layout constants (88 bytes total):
    # id:U32, zone:U8, sensor:U8, length:U16, drop_box:U16, flags:2, buttons:64 (interleaved), dtl:12
    _LEGACY_HEADER_STRUCT: ClassVar[struct.Struct] = struct.Struct(">IBBHH")
    _LEGACY_FLAGS_SIZE: ClassVar[int] = 2
    _LEGACY_BUTTONS_SIZE: ClassVar[int] = 64  # interleaved pairs order,count
    LEGACY_BYTE_SIZE: ClassVar[int] = (
        _LEGACY_HEADER_STRUCT.size + _LEGACY_FLAGS_SIZE + _LEGACY_BUTTONS_SIZE + DTL._STRUCT.size
    )

    def __post_init__(self) -> None:
        flags = tuple(bool(flag) for flag in self.flags)
        if len(flags) != self.FLAGS_COUNT:
            raise ValueError(f"flags must contain {self.FLAGS_COUNT} entries")
        object.__setattr__(self, "flags", flags)

        buttons = tuple(int(button) for button in self.buttons)
        if len(buttons) != self._BUTTONS_BYTE_SIZE:
            raise ValueError(
                f"buttons must contain {self._BUTTONS_BYTE_SIZE} entries (32 + 32)"
            )
        if any(button < 0 or button > 0xFF for button in buttons):
            raise ValueError("button bytes must be in range 0-255")
        object.__setattr__(self, "buttons", buttons)

        if self.id < 0:
            raise ValueError("id must be non-negative")
        if not (0 <= self.zone_id <= 0xFF):
            raise ValueError("zone_id must fit in an unsigned byte")
        if not (0 <= self.sensor_id <= 0xFF):
            raise ValueError("sensor_id must fit in an unsigned byte")
        if not (0 <= self.length <= 0xFFFF):
            raise ValueError("length must fit in an unsigned word")
        if not (0 <= self.position <= 0xFFFFFFFF):
            raise ValueError("position must fit in an unsigned double word")
        if not (0 <= self.drop_box_number <= 0xFFFF):
            raise ValueError("drop_box_number must fit in an unsigned word")

    def to_bytes(self) -> bytes:
        """Serialize the structure into the packed PLC representation."""

        header = self._HEADER_STRUCT.pack(
            self.id,
            self.zone_id,
            self.sensor_id,
            self.length,
            self.position,
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
            position=header[4],
            drop_box_number=header[5],
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

    # -- compatibility helpers -------------------------------------------------
    @classmethod
    def from_legacy_bytes(cls, payload: bytes) -> "SAWLOG":
        """Parse the legacy 88-byte SAWLOG and map to the new shape.

        - sensor_id stays U8
        - position is set to 0 (field did not exist)
        - 16 flags are padded with another 16 as False
        - buttons are converted from interleaved pairs to [first32 + next32]
        """

        if len(payload) != cls.LEGACY_BYTE_SIZE:
            raise ValueError("legacy SAWLOG payload must be 88 bytes")
        off = 0
        h = cls._LEGACY_HEADER_STRUCT.unpack_from(payload, off)
        off += cls._LEGACY_HEADER_STRUCT.size
        flags2 = payload[off : off + cls._LEGACY_FLAGS_SIZE]
        off += cls._LEGACY_FLAGS_SIZE
        buttons_inter = payload[off : off + cls._LEGACY_BUTTONS_SIZE]
        off += cls._LEGACY_BUTTONS_SIZE
        ts = DTL.from_bytes(payload[off : off + DTL._STRUCT.size])

        # flags: 16 bits -> pad to 32
        val = int.from_bytes(flags2, byteorder="big")
        flags0 = tuple(bool(val & (1 << i)) for i in range(16))
        flags_full = flags0 + (False,) * 16

        # buttons: interleaved -> first32 + next32
        orders = [buttons_inter[2 * i] for i in range(32)]
        counts = [buttons_inter[2 * i + 1] for i in range(32)]
        buttons_new = tuple(int(b) for b in (orders + counts))

        return cls(
            id=h[0],
            zone_id=h[1],
            sensor_id=h[2],
            length=h[3],
            position=0,
            drop_box_number=h[4],
            flags=flags_full,
            buttons=buttons_new,
            timestamp=ts,
        )

    @classmethod
    def array_from_bytes_compat(cls, payload: bytes) -> Tuple["SAWLOG", ...]:
        """Parse as new layout (94B) when possible, otherwise legacy (88B)."""

        if len(payload) == 0:
            return tuple()
        if len(payload) % cls.BYTE_SIZE == 0:
            return cls.array_from_bytes(payload)
        if len(payload) % cls.LEGACY_BYTE_SIZE == 0:
            recs = []
            view = memoryview(payload)
            for offset in range(0, len(payload), cls.LEGACY_BYTE_SIZE):
                chunk = view[offset : offset + cls.LEGACY_BYTE_SIZE]
                recs.append(cls.from_legacy_bytes(bytes(chunk)))
            return tuple(recs)
        raise ValueError("payload length is neither a multiple of 94 nor 88 bytes")

    @staticmethod
    def _pack_flags(flags: Tuple[bool, ...]) -> bytes:
        if len(flags) != SAWLOG.FLAGS_COUNT:
            raise ValueError("flags payload must have 32 entries")
        # two words, big-endian; lower 16 bits = FL0..15, upper 16 bits = FL16..31
        low = 0
        high = 0
        for index in range(16):
            if flags[index]:
                low |= 1 << index
        for index in range(16, 32):
            if flags[index]:
                high |= 1 << (index - 16)
        return low.to_bytes(2, byteorder="big") + high.to_bytes(2, byteorder="big")

    @staticmethod
    def _unpack_flags(payload: bytes) -> Tuple[bool, ...]:
        if len(payload) != SAWLOG._FLAGS_BYTE_SIZE:
            raise ValueError("flags payload has invalid length")
        low = int.from_bytes(payload[0:2], byteorder="big")
        high = int.from_bytes(payload[2:4], byteorder="big")
        flags0 = tuple(bool(low & (1 << i)) for i in range(16))
        flags1 = tuple(bool(high & (1 << i)) for i in range(16))
        return flags0 + flags1

    @staticmethod
    def _pack_buttons(buttons: Tuple[int, ...]) -> bytes:
        # buttons represent 64 raw bytes: first 32 then 32
        if len(buttons) != SAWLOG._BUTTONS_BYTE_SIZE:
            raise ValueError("buttons payload has invalid length")
        return bytes(byte & 0xFF for byte in buttons)

    @staticmethod
    def _unpack_buttons(payload: bytes) -> Tuple[int, ...]:
        if len(payload) != SAWLOG._BUTTONS_BYTE_SIZE:
            raise ValueError("buttons payload has invalid length")
        # Return as 64 raw bytes: first 32 then next 32
        return tuple(int(b) for b in payload)


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
