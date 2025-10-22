from __future__ import annotations

from typing import Tuple

from plc_client import PLCClient, SAWLOG, SawlogsRegisterDB

Records = Tuple[SAWLOG, ...]


def fetch_payload_and_records(
    client: PLCClient, db: int, start: int, size: int
):
    """Read from PLC and return (payload, records|None).

    - If the range matches the full SAWLOG register (offset 0, full size), use the
      high-level register API and return both bytes and typed records.
    - Otherwise read raw DB bytes; if the length is a multiple of SAWLOG size, try to
      parse it into SAWLOG records. Return None on parse mismatch.
    """

    if start == 0 and size == SawlogsRegisterDB.DB_BYTE_SIZE:
        register = client.read_sawlog_register(db)
        return bytearray(register.to_bytes()), register.records

    payload = client.read_db(db, start, size)
    records: Records | None = None
    if len(payload) > 0:
        try:
            records = SAWLOG.array_from_bytes_compat(bytes(payload))
        except ValueError:
            records = None
    return payload, records
