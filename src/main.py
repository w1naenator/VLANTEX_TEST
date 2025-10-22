"""Simple entrypoint for reading data from an S7-200SP PLC."""

from __future__ import annotations

import argparse
import sys
from typing import Iterable, Sequence, Tuple

from plc_client import PLCClient, PLCConfig, SAWLOG, SawlogsRegisterDB
from plc_client.readers import fetch_payload_and_records
from gui import PLCReaderApp
Records = Tuple[SAWLOG, ...]
MAX_PREVIEW_BYTES = 32


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read bytes from a Siemens PLC")
    parser.add_argument("address", help="PLC IP address or hostname")
    parser.add_argument("db", type=int, help="Data block number")
    parser.add_argument("start", type=int, help="Start offset in bytes")
    parser.add_argument("size", type=int, help="Number of bytes to read")
    parser.add_argument("--rack", type=int, default=0, help="Rack number (default: 0)")
    parser.add_argument("--slot", type=int, default=1, help="Slot number (default: 1)")
    parser.add_argument(
        "--tcp-port",
        dest="tcp_port",
        type=int,
        default=102,
        help="ISO-on-TCP port (default: 102)",
    )
    return parser.parse_args(argv)


def summarise_sawlogs(records: Iterable[SAWLOG]) -> Tuple[str, ...]:
    lines = []
    for index, record in enumerate(records):
        timestamp = record.timestamp.to_datetime().isoformat(sep=" ")
        flags = "".join("1" if flag else "0" for flag in record.flags)
        # Show first 5 buttons as order,count pairs (interleaved)
        try:
            pair_preview = [
                f"{int(record.buttons[2*i])},{int(record.buttons[2*i+1])}"
                for i in range(5)
            ]
            buttons_preview = " ".join(pair_preview)
            buttons_preview += " ..."
        except Exception:
            buttons_preview = ""
        lines.append(
            f"[{index:03}] id={record.id} zone={record.zone_id} sensor={record.sensor_id} "
            f"length={record.length} drop_box={record.drop_box_number} "
            f"flags={flags} buttons={buttons_preview} timestamp={timestamp}"
        )
    return tuple(lines)


def summarise_payload(
    payload: bytearray,
    db: int,
    start: int,
    *,
    sawlog_records: Records | None = None,
) -> str:
    size = len(payload)
    lines = [f"Read {size} byte(s) from DB{db} @ {start}."]

    if size == 0:
        lines.append("Payload is empty.")
        return "\n".join(lines)

    preview_len = min(size, MAX_PREVIEW_BYTES)
    preview = payload[:preview_len].hex(" ")
    if size > preview_len:
        preview += " ..."
    lines.append(f"Hex preview ({preview_len} byte(s)): {preview}")

    parsed_records: Records | None = sawlog_records

    if parsed_records is None and size % SAWLOG.BYTE_SIZE == 0:
        try:
            parsed_records = SAWLOG.array_from_bytes(bytes(payload))
        except ValueError:
            parsed_records = None

    if parsed_records:
        count = len(parsed_records)
        lines.append(f"Parsed {count} SAWLOG record(s).")
        preview_count = min(count, 5)
        lines.extend(summarise_sawlogs(parsed_records[:preview_count]))
        if count > preview_count:
            lines.append("...")

        if count == SawlogsRegisterDB.CAPACITY:
            lines.append(
                f"Interpreted as full SAWLOG register ({SawlogsRegisterDB.CAPACITY} entries, "
                f"{SawlogsRegisterDB.DB_BYTE_SIZE} bytes)."
            )
    else:
        if size % SAWLOG.BYTE_SIZE != 0:
            lines.append(
                f"Payload length is not a multiple of SAWLOG size ({SAWLOG.BYTE_SIZE} bytes); "
                "skipping structured parse."
            )

    return "\n".join(lines)


def run_cli(args: argparse.Namespace) -> None:
    config = PLCConfig(
        address=args.address,
        rack=args.rack,
        slot=args.slot,
        tcp_port=args.tcp_port,
    )

    with PLCClient(config) as client:
        payload, records = fetch_payload_and_records(
            client, args.db, args.start, args.size
        )
        message = summarise_payload(payload, args.db, args.start, sawlog_records=records)
        print(message)


def launch_gui() -> None:
    PLCReaderApp().run()


def main(argv: Sequence[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]

    if argv:
        args = parse_args(argv)
        run_cli(args)
    else:
        launch_gui()


if __name__ == "__main__":  # pragma: no cover
    main()
