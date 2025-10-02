"""Simple entrypoint for reading data from an S7-200SP PLC."""

from __future__ import annotations

import argparse
import sys
import threading
from typing import Iterable, Sequence, Tuple, Optional

from plc_client import PLCClient, PLCConfig, SAWLOG, SawlogsRegisterDB

DEFAULT_ADDRESS = "192.168.61.110"
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
        buttons_preview = " ".join(f"{button:X}" for button in record.buttons[:8])
        if len(record.buttons) > 8:
            buttons_preview += " ..."
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


def fetch_payload_and_records(
    client: PLCClient, db: int, start: int, size: int
) -> Tuple[bytearray, Records | None]:
    """Read from PLC and return raw payload plus parsed SAWLOG records if applicable.

    - If range matches full register (offset 0, full size), uses read_sawlog_register
      to obtain both payload and typed records.
    - Otherwise reads raw DB bytes; if the length is a multiple of SAWLOG size, attempts
      to parse into records; returns None on parse mismatch.
    """
    if start == 0 and size == SawlogsRegisterDB.DB_BYTE_SIZE:
        register = client.read_sawlog_register(db)
        return bytearray(register.to_bytes()), register.records
    payload = client.read_db(db, start, size)
    records: Records | None = None
    if len(payload) > 0 and (len(payload) % SAWLOG.BYTE_SIZE == 0):
        try:
            records = SAWLOG.array_from_bytes(bytes(payload))
        except ValueError:
            records = None
    return payload, records


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
    import tkinter as tk
    from tkinter import messagebox, ttk

    class PLCReaderApp:
        def __init__(self) -> None:
            self.root = tk.Tk()
            self.root.title("Siemens PLC Reader")

            self.address_var = tk.StringVar(value=DEFAULT_ADDRESS)
            self.db_var = tk.StringVar(value="200")
            self.start_var = tk.StringVar(value="0")
            self.size_var = tk.StringVar(value=str(SawlogsRegisterDB.DB_BYTE_SIZE))
            self.rack_var = tk.StringVar(value="0")
            self.slot_var = tk.StringVar(value="1")
            self.tcp_port_var = tk.StringVar(value="102")
            self.status_var = tk.StringVar(value="Ready")

            self._is_busy = False
            self._records_cache: Tuple[SAWLOG, ...] | None = None

            self._build_ui()

            # Make the initial window approximately 2x wider
            self._double_window_width()

        def _build_ui(self) -> None:
            self.root.columnconfigure(0, weight=1)
            self.root.rowconfigure(0, weight=1)

            frame = ttk.Frame(self.root, padding=12)
            frame.grid(row=0, column=0, sticky="nsew")

            labels = [
                ("Address", self.address_var),
                ("DB", self.db_var),
                ("Start", self.start_var),
                ("Size", self.size_var),
                ("Rack", self.rack_var),
                ("Slot", self.slot_var),
                ("TCP Port", self.tcp_port_var),
            ]

            for row, (label, var) in enumerate(labels):
                ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
                ttk.Entry(frame, textvariable=var, width=24).grid(
                    row=row, column=1, sticky="ew", pady=2
                )

            frame.columnconfigure(1, weight=1)

            self.read_button = ttk.Button(frame, text="Read Data", command=self.on_read)
            self.read_button.grid(row=len(labels), column=0, columnspan=2, pady=(8, 4), sticky="ew")

            ttk.Label(frame, textvariable=self.status_var).grid(
                row=len(labels) + 1, column=0, columnspan=2, sticky="w"
            )

            # Notebook with two tabs: SAWLOG Overview and Text summary
            self.notebook = ttk.Notebook(frame)
            self.notebook.grid(
                row=len(labels) + 2, column=0, columnspan=2, pady=(4, 0), sticky="nsew"
            )

            # Overview tab with table (first tab)
            self.overview_tab = ttk.Frame(self.notebook)
            self._build_overview_table(self.overview_tab)
            self.notebook.add(self.overview_tab, text="Overview")

            # Text summary tab (second tab)
            self.text_tab = ttk.Frame(self.notebook)
            self.result_box = tk.Text(self.text_tab, height=16, width=50, state="disabled")
            self.result_box.pack(fill="both", expand=True)
            self.notebook.add(self.text_tab, text="Text")

            # Ensure Overview is the initially selected tab
            self.notebook.select(self.overview_tab)

            frame.rowconfigure(len(labels) + 2, weight=1)

        def _build_overview_table(self, parent) -> None:
            columns = (
                "Index",
                "ID",
                "Zone",
                "Sensor",
                "Length",
                "DropBox",
                "Flags",
                "Buttons",
                "Timestamp",
            )
            container = ttk.Frame(parent)
            container.pack(fill="both", expand=True)

            self.tree = ttk.Treeview(
                container,
                columns=columns,
                show="headings",
                selectmode="browse",
                height=15,
            )
            vsb = ttk.Scrollbar(container, orient="vertical", command=self.tree.yview)
            hsb = ttk.Scrollbar(container, orient="horizontal", command=self.tree.xview)
            self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)

            self.tree.grid(row=0, column=0, sticky="nsew")
            vsb.grid(row=0, column=1, sticky="ns")
            hsb.grid(row=1, column=0, columnspan=2, sticky="ew")

            container.rowconfigure(0, weight=1)
            container.columnconfigure(0, weight=1)

            headings = {
                "Index": ("#", 50),
                "ID": ("ID", 100),
                "Zone": ("Zone", 60),
                "Sensor": ("Sensor", 70),
                "Length": ("Length", 80),
                "DropBox": ("DropBox", 90),
                "Flags": ("Flags", 80),
                "Buttons": ("Buttons", 160),
                "Timestamp": ("Timestamp", 180),
            }
            for col in columns:
                text, width = headings[col]
                self.tree.heading(col, text=text)
                self.tree.column(col, width=width, anchor="center")

            self.tree.bind("<Double-1>", self._on_row_double_click)

        def _double_window_width(self) -> None:
            # Compute current geometry then set width to 2x
            self.root.update_idletasks()
            width = self.root.winfo_width() or self.root.winfo_reqwidth()
            height = self.root.winfo_height() or self.root.winfo_reqheight()
            try:
                new_width = max(int(width * 2), width + 1)
                self.root.geometry(f"{new_width}x{height}")
            except Exception:
                # If geometry fails for any reason, ignore and keep defaults
                pass

        def on_read(self) -> None:
            if self._is_busy:
                return

            try:
                db = int(self.db_var.get())
                start = int(self.start_var.get())
                size = int(self.size_var.get())
                rack = int(self.rack_var.get())
                slot = int(self.slot_var.get())
                tcp_port = int(self.tcp_port_var.get())
            except ValueError:
                messagebox.showerror("Invalid input", "DB, start, size, rack, slot, and TCP port must be numbers.")
                return

            try:
                config = PLCConfig(
                    address=self.address_var.get().strip(),
                    rack=rack,
                    slot=slot,
                    tcp_port=tcp_port,
                )
            except ValueError as exc:
                messagebox.showerror("Invalid configuration", str(exc))
                return

            self._set_busy(True)
            self._set_status("Reading...")
            threading.Thread(
                target=self._read_worker,
                args=(config, db, start, size),
                daemon=True,
            ).start()

        def _read_worker(self, config: PLCConfig, db: int, start: int, size: int) -> None:
            try:
                with PLCClient(config) as client:
                    payload, records = fetch_payload_and_records(client, db, start, size)
                message = summarise_payload(payload, db, start, sawlog_records=records)
                self._post_result_with_records(message, records, success=True)
            except Exception as exc:  # snap7 raises RuntimeError on failure
                self._post_result_with_records(f"Error: {exc}", None, success=False)

        def _post_result_with_records(
            self, message: str, records: Tuple[SAWLOG, ...] | None, *, success: bool
        ) -> None:
            self.root.after(
                0, lambda: self._update_ui_after_result_with_records(message, records, success)
            )

        def _update_ui_after_result_with_records(
            self, message: str, records: Tuple[SAWLOG, ...] | None, success: bool
        ) -> None:
            self._set_busy(False)
            if success:
                self._set_status("Completed")
            else:
                self._set_status("Failed")
            self._set_result(message)
            self._populate_overview(records)

        def _set_busy(self, busy: bool) -> None:
            self._is_busy = busy
            state = "disabled" if busy else "normal"
            self.read_button.configure(state=state)

        def _set_status(self, text: str) -> None:
            self.status_var.set(text)

        def _set_result(self, message: str) -> None:
            self.result_box.configure(state="normal")
            self.result_box.delete("1.0", tk.END)
            self.result_box.insert(tk.END, message)
            self.result_box.configure(state="disabled")

        def _populate_overview(self, records: Tuple[SAWLOG, ...] | None) -> None:
            # Clear previous rows
            if not hasattr(self, "tree"):
                return
            for item in self.tree.get_children():
                self.tree.delete(item)
            self._records_cache = tuple(records) if records else None
            if not records:
                return
            for index, record in enumerate(records):
                # Pack flags as hex word for concise overview
                flags_value = 0
                for i, flag in enumerate(record.flags):
                    if flag:
                        flags_value |= (1 << i)
                flags_hex = f"0x{flags_value:04X}"
                buttons_preview = " ".join(f"{b:X}" for b in record.buttons[:8])
                if len(record.buttons) > 8:
                    buttons_preview += " ..."
                timestamp = record.timestamp.to_datetime().isoformat(sep=" ")
                self.tree.insert(
                    "",
                    "end",
                    iid=str(index),
                    values=(
                        index,
                        record.id,
                        record.zone_id,
                        record.sensor_id,
                        record.length,
                        record.drop_box_number,
                        flags_hex,
                        buttons_preview,
                        timestamp,
                    ),
                )

        def _on_row_double_click(self, _event=None) -> None:
            selection = self.tree.selection()
            if not selection or self._records_cache is None:
                return
            try:
                index = int(selection[0])
            except ValueError:
                # Fallback using position
                index = self.tree.index(selection[0])
            if 0 <= index < len(self._records_cache):
                self._show_record_details(index, self._records_cache[index])

        def _show_record_details(self, index: int, record: SAWLOG) -> None:
            win = tk.Toplevel(self.root)
            win.title(f"SAWLOG [{index}] Details")
            win.transient(self.root)

            # Header fields
            header_frame = ttk.LabelFrame(win, text="Header")
            header_frame.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=8, pady=8)
            fields = [
                ("ID", record.id),
                ("Zone", record.zone_id),
                ("Sensor", record.sensor_id),
                ("Length", record.length),
                ("DropBox", record.drop_box_number),
                ("Timestamp", record.timestamp.to_datetime().isoformat(sep=" ")),
            ]
            for r, (label, value) in enumerate(fields):
                ttk.Label(header_frame, text=f"{label}:").grid(row=r, column=0, sticky="w", padx=6, pady=2)
                ttk.Label(header_frame, text=str(value)).grid(row=r, column=1, sticky="w", padx=6, pady=2)
            header_frame.columnconfigure(1, weight=1)

            # Flags grid as table with 8 columns and row headers 0, 8 (with borders & highlighted headers)
            flags_frame = ttk.LabelFrame(win, text="Flags (FL0..FL15)")
            flags_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=8)
            import tkinter.font as tkfont

            base_font = tkfont.nametofont("TkDefaultFont")
            header_font = base_font.copy()
            header_font.configure(weight="bold")

            def add_cell(parent, text, row, col, *, header=False, width=3):
                bg = "#e8eefc" if header else None
                lbl = tk.Label(
                    parent,
                    text=str(text),
                    bd=1,
                    relief="solid",
                    padx=4,
                    pady=2,
                    width=width,
                    bg=bg,
                )
                if header:
                    lbl.configure(font=header_font)
                lbl.grid(row=row, column=col, sticky="nsew")

            # Column headers 0..7
            add_cell(flags_frame, "", 0, 0, header=True, width=3)  # corner
            for c in range(8):
                add_cell(flags_frame, c, 0, c + 1, header=True, width=3)

            # Rows with row headers 0, 8
            for r in range(2):
                add_cell(flags_frame, r * 8, r + 1, 0, header=True, width=3)
                for c in range(8):
                    idx = r * 8 + c
                    val = 1 if record.flags[idx] else 0
                    add_cell(flags_frame, val, r + 1, c + 1, width=3)

            for c in range(9):
                flags_frame.columnconfigure(c, weight=1)
            for r in range(3):
                flags_frame.rowconfigure(r, weight=1)

            # Buttons grid 64 nibbles in 8x8 with row/col headers (with borders & highlighted headers)
            buttons_frame = ttk.LabelFrame(win, text="Buttons (BT0..BT63)")
            buttons_frame.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)
            # Column headers 0..7
            add_cell(buttons_frame, "", 0, 0, header=True, width=3)  # corner
            for c in range(8):
                add_cell(buttons_frame, c, 0, c + 1, header=True, width=3)

            # Rows with row headers 0,8,16,24,32,40,48,56
            for r in range(8):
                add_cell(buttons_frame, r * 8, r + 1, 0, header=True, width=3)
                for c in range(8):
                    idx = r * 8 + c
                    val = int(record.buttons[idx])
                    add_cell(buttons_frame, val, r + 1, c + 1, width=3)

            for c in range(9):
                buttons_frame.columnconfigure(c, weight=1)
            for r in range(9):
                buttons_frame.rowconfigure(r, weight=1)

            win.columnconfigure(0, weight=1)
            win.columnconfigure(1, weight=1)
            win.rowconfigure(1, weight=1)

        def run(self) -> None:
            self.root.mainloop()

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
