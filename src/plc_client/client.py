"""Client wrapper for communicating with Siemens S7 PLCs."""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Dict, Iterable, Optional, Tuple

from snap7 import client as snap7_client

try:
    from snap7 import types as _snap7_types
except ImportError:  # python-snap7>=1.3 renames the module to `type`
    from snap7 import type as _snap7_types  # type: ignore[attr-defined]

try:
    from snap7.snap7exceptions import Snap7Exception  # python-snap7<=1.2
except ModuleNotFoundError:  # python-snap7>=1.3 raises RuntimeError instead
    Snap7Exception = RuntimeError  # type: ignore[misc,assignment]

from .config import PLCConfig
from .datatypes import SAWLOG, SawlogsRegisterDB

snap7_types = _snap7_types

Request = Tuple[int, int, int]


class PLCClient(AbstractContextManager["PLCClient"]):
    """High-level PLC client using the snap7 library."""

    def __init__(self, config: PLCConfig) -> None:
        self._config = config
        self._client: Optional[snap7_client.Client] = None

    # -- context manager protocol -------------------------------------------------
    def __enter__(self) -> "PLCClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, exc_tb) -> None:
        self.disconnect()

    # -- connection management ----------------------------------------------------
    @property
    def is_connected(self) -> bool:
        return bool(self._client and self._client.get_connected())

    def connect(self) -> None:
        if self.is_connected:
            return

        client = snap7_client.Client()
        try:
            client.set_connection_type(0x02)  # basic S7 communication
        except AttributeError:
            # Older snap7 releases may not expose set_connection_type; ignore.
            pass

        connect_args = (
            self._config.address,
            self._config.rack,
            self._config.slot,
        )

        try:
            client.connect(*connect_args, tcp_port=self._config.tcp_port)
        except TypeError as exc:
            if "tcp_port" not in str(exc):
                raise
            client.connect(*connect_args, tcpport=self._config.tcp_port)

        self._client = client

    def disconnect(self) -> None:
        if not self._client:
            return
        try:
            self._client.disconnect()
        finally:
            self._client.destroy()
            self._client = None

    def ensure_connected(self) -> None:
        if not self.is_connected:
            raise RuntimeError("client is not connected to the PLC")

    # -- data access ----------------------------------------------------------------
    def read_db(self, db_number: int, start: int, size: int) -> bytearray:
        """Read raw bytes from a PLC data block."""

        self.ensure_connected()
        assert self._client is not None  # for type-checkers
        try:
            return bytearray(self._client.db_read(db_number, start, size))
        except Snap7Exception as exc:
            raise RuntimeError(
                f"Failed to read DB{db_number} offset {start} size {size}: {exc}"
            ) from exc

    def write_db(self, db_number: int, start: int, data: bytes | bytearray) -> None:
        """Write raw bytes to a PLC data block."""

        self.ensure_connected()
        assert self._client is not None  # for type-checkers
        try:
            # snap7 expects a bytearray-like buffer
            buf = bytearray(data)
            self._client.db_write(db_number, start, buf)
        except Snap7Exception as exc:
            raise RuntimeError(
                f"Failed to write DB{db_number} offset {start} size {len(data)}: {exc}"
            ) from exc

    def read_inputs(self, start: int, size: int) -> bytearray:
        """Read from the inputs (I area)."""

        self.ensure_connected()
        assert self._client is not None
        try:
            return bytearray(
                self._client.read_area(snap7_types.Areas.PE, 0, start, size)
            )
        except Snap7Exception as exc:
            raise RuntimeError(f"Failed to read inputs: {exc}") from exc

    def read_outputs(self, start: int, size: int) -> bytearray:
        """Read from the outputs (Q area)."""

        self.ensure_connected()
        assert self._client is not None
        try:
            return bytearray(
                self._client.read_area(snap7_types.Areas.PA, 0, start, size)
            )
        except Snap7Exception as exc:
            raise RuntimeError(f"Failed to read outputs: {exc}") from exc

    def read_sawlog_register(
        self, db_number: int = 200, start: int = 0
    ) -> SawlogsRegisterDB:
        """Read the full SAWLOG register data block (255 records)."""

        size = SawlogsRegisterDB.DB_BYTE_SIZE
        payload = self.read_db(db_number, start, size)
        if len(payload) != size:
            raise RuntimeError(
                f"Expected {size} bytes when reading SAWLOG register, received {len(payload)}"
            )
        return SawlogsRegisterDB.from_bytes(bytes(payload))

    def write_sawlog_record(
        self, db_number: int, index: int, record: SAWLOG, *, start: int = 0
    ) -> None:
        """Write a single SAWLOG record at the given index (0-based)."""

        if index < 0:
            raise ValueError("index must be non-negative")
        offset = start + index * SAWLOG.BYTE_SIZE
        self.write_db(db_number, offset, record.to_bytes())

    def bulk_read(self, requests: Iterable[Request]) -> Dict[Request, bytearray]:
        """Perform multiple DB reads and return a mapping of request -> bytes."""

        return {request: self.read_db(*request) for request in requests}
