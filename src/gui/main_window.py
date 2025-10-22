from __future__ import annotations

from typing import Optional, Tuple

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from plc_client import PLCClient, PLCConfig, SAWLOG
from plc_client.readers import fetch_payload_and_records
from .detail_window import DetailWindow
from .settings_window import SettingsWindow
from .app_settings import AppSettings, load_settings


class PLCReaderApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Siemens PLC Reader")

        # Connection settings kept in separate window; still stored in vars
        self._settings = load_settings()
        self.address_var = tk.StringVar(value=self._settings.address)
        self.db_var = tk.StringVar(value=str(self._settings.db))
        self.start_var = tk.StringVar(value=str(self._settings.start))
        self.size_var = tk.StringVar(value=str(self._settings.size))
        self.rack_var = tk.StringVar(value=str(self._settings.rack))
        self.slot_var = tk.StringVar(value=str(self._settings.slot))
        self.tcp_port_var = tk.StringVar(value=str(self._settings.tcp_port))
        self.status_var = tk.StringVar(value="Unknown")

        self._is_busy = False
        self._reader_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._client: Optional[PLCClient] = None
        self._input_widgets: list[tk.Widget] = []
        self._records_cache: Tuple[SAWLOG, ...] | None = None
        self._detail_window: Optional[DetailWindow] = None
        self._pending_start: Optional[tuple] = None  # holds args for _start_reader on restart

        self._build_ui()
        self._set_initial_geometry()

    # -- UI build ---------------------------------------------------------------
    def _build_ui(self) -> None:
        # Configure top (toolbar) + main content rows
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=0)
        self.root.rowconfigure(1, weight=1)

        # Menubar
        menubar = tk.Menu(self.root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Connect", command=self.on_connect_toggle)
        file_menu.add_command(label="Settings...", command=self._open_settings)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.root.destroy)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(
            label="About",
            command=lambda: messagebox.showinfo(
                "About",
                "Siemens PLC Reader\nCyclic read with overview and console.",
                parent=self.root,
            ),
        )
        menubar.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menubar)
        self._menubar = menubar
        self._file_menu = file_menu
        self._file_menu_connect_index = 0

        # Toolbar with status indicator
        toolbar = ttk.Frame(self.root, padding=(8, 4))
        toolbar.grid(row=0, column=0, sticky="ew")
        ttk.Label(toolbar, text="Status:").pack(side="left")
        self.status_indicator = tk.Label(toolbar, text="●", fg="#6a737d")
        self.status_indicator.pack(side="left", padx=(6, 4))
        self.status_text = ttk.Label(toolbar, textvariable=self.status_var)
        self.status_text.pack(side="left")

        # Main content frame
        frame = ttk.Frame(self.root, padding=12)
        frame.grid(row=1, column=0, sticky="nsew")
        self._frame = frame

        labels: list[tuple[str, tk.StringVar]] = []
        self.interval_var = tk.StringVar(value=str(self._settings.interval_ms))

        for row, (label, var) in enumerate(labels):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
            entry = ttk.Entry(frame, textvariable=var, width=24)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            self._input_widgets.append(entry)

        frame.columnconfigure(1, weight=1)

        # No connect button in main window; use menu and status label instead

        # Notebook with two tabs: Overview and Console
        self.notebook = ttk.Notebook(frame)
        # Place notebook at first row since there are no inputs above
        self.notebook.grid(row=0, column=0, columnspan=2, pady=(4, 0), sticky="nsew")

        # Overview tab
        self.overview_tab = ttk.Frame(self.notebook)
        self._build_overview_table(self.overview_tab)
        self.notebook.add(self.overview_tab, text="Overview")

        # Console tab
        self.text_tab = ttk.Frame(self.notebook)
        self.result_box = tk.Text(self.text_tab, height=16, width=50, state="disabled")
        self.result_box.pack(fill="both", expand=True)
        self.notebook.add(self.text_tab, text="Console")

        self.notebook.select(self.overview_tab)
        self._apply_status_state("Unknown")

        # Only notebook in frame; make its row stretch
        frame.rowconfigure(0, weight=1)
        # Make status label toggle connection on double-click
        self.status_text.bind("<Double-1>", lambda _e: self.on_connect_toggle())

    def _open_settings(self) -> None:
        if getattr(self, "_settings_win", None) is not None:
            try:
                self._settings_win._close()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._settings_win = None

        current = AppSettings(
            address=self.address_var.get().strip(),
            rack=int(self.rack_var.get()),
            slot=int(self.slot_var.get()),
            tcp_port=int(self.tcp_port_var.get()),
            db=int(self.db_var.get()),
            start=int(self.start_var.get()),
            size=int(self.size_var.get()),
            interval_ms=int(self.interval_var.get()),
        )

        def apply_cb(new_settings: AppSettings, saved: bool) -> None:
            # Update vars in main window
            self.address_var.set(new_settings.address)
            self.rack_var.set(str(new_settings.rack))
            self.slot_var.set(str(new_settings.slot))
            self.tcp_port_var.set(str(new_settings.tcp_port))
            self._console_log(
                f"Settings {'saved' if saved else 'applied'}: {new_settings.address}:{new_settings.tcp_port}"
            )
            if saved:
                self._console_log("Settings persisted to JSON next to launcher.")
            # Update DB and interval vars
            self.db_var.set(str(new_settings.db))
            self.start_var.set(str(new_settings.start))
            self.size_var.set(str(new_settings.size))
            self.interval_var.set(str(new_settings.interval_ms))
            # Make settings effective immediately: if running, restart reader with new params
            try:
                self._schedule_restart_with(new_settings)
            except Exception:
                pass

        self._settings_win = SettingsWindow(self.root, current, apply_cb)

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
        # Use a monospaced font in the table so glyphs align uniformly
        try:
            style = ttk.Style(self.root)
            style.configure("Monospace.Treeview", font=("Consolas", 10))
            self.tree.configure(style="Monospace.Treeview")
        except Exception:
            pass
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
            "Flags": ("Flags", 120),
            "Buttons": ("Buttons", 900),
            "Timestamp": ("Timestamp", 180),
        }
        for col in columns:
            text, width = headings[col]
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, anchor="center")

        self.tree.bind("<Double-1>", self._on_row_double_click)

    def _set_initial_geometry(self) -> None:
        try:
            self.root.geometry("1920x1080")
        except Exception:
            pass

    # -- Connect / loop ---------------------------------------------------------
    def on_connect_toggle(self) -> None:
        if self._reader_thread and self._reader_thread.is_alive():
            # Confirm disconnection
            if not messagebox.askyesno("Disconnect", "Do you want to disconnect?", parent=self.root):
                return
            # Clear table immediately on user-initiated disconnect
            self._clear_overview_rows()
            self._stop_event.set()
            return

        try:
            db = int(self.db_var.get())
            start = int(self.start_var.get())
            size = int(self.size_var.get())
            interval_ms = int(self.interval_var.get())
            rack = int(self.rack_var.get())
            slot = int(self.slot_var.get())
            tcp_port = int(self.tcp_port_var.get())
        except ValueError:
            messagebox.showerror(
                "Invalid input",
                "DB, start, size, interval, rack, slot, and TCP port must be numbers.",
                parent=self.root,
            )
            return

        try:
            config = PLCConfig(
                address=self.address_var.get().strip(),
                rack=rack,
                slot=slot,
                tcp_port=tcp_port,
            )
        except ValueError as exc:
            messagebox.showerror("Invalid configuration", str(exc), parent=self.root)
            return

        self._start_reader(config, db, start, size, interval_ms)

    def _start_reader(self, config: PLCConfig, db: int, start: int, size: int, interval_ms: int) -> None:
        if self._reader_thread and self._reader_thread.is_alive():
            return
        self._stop_event.clear()
        self._console_log(
            f"Connecting to {config.address}:{config.tcp_port} (DB{db} @{start} size {size})..."
        )
        self._set_online(False)
        self._set_controls_enabled(False)
        try:
            self._file_menu.entryconfig(self._file_menu_connect_index, label="Disconnect")
        except Exception:
            pass

        def loop() -> None:
            import time as _time
            backoff = 1.0
            client = PLCClient(config)
            try:
                while not self._stop_event.is_set():
                    try:
                        if not client.is_connected:
                            client.connect()
                            self._post_online(True)
                            self._console_log(f"Connected to {config.address}:{config.tcp_port}")
                            backoff = 1.0
                        payload, records = fetch_payload_and_records(client, db, start, size)
                        self._console_log(f"Read {len(payload)} byte(s) from DB{db} @ {start}")
                        self._post_result_with_records("", records, success=True)
                    except Exception as exc:
                        # Unexpected disconnect: mark offline but keep last data in table
                        self._post_handle_disconnect(clear_table=False)
                        self._console_log(f"Connection error: {exc}. Retrying...")
                        try:
                            client.disconnect()
                        except Exception:
                            pass
                        _time.sleep(min(backoff, 5.0))
                        backoff = min(backoff * 2.0, 5.0)
                        continue
                    delay = max(0, interval_ms) / 1000.0
                    for _ in range(max(1, int(delay * 10))):
                        if self._stop_event.is_set():
                            break
                        _time.sleep(0.1)
            finally:
                try:
                    if client.is_connected:
                        client.disconnect()
                except Exception:
                    pass
                # On final disconnect, clear table only if not immediately restarting
                self._post_handle_disconnect(clear_table=(self._pending_start is None))
                self._console_log("Disconnected")
                self.root.after(0, self._reset_controls_after_disconnect)

        self._reader_thread = threading.Thread(target=loop, daemon=True)
        self._reader_thread.start()

    def _reset_controls_after_disconnect(self) -> None:
        # If there's a pending restart, start it now instead of returning to idle
        if self._pending_start is not None:
            args = self._pending_start
            self._pending_start = None
            # Start with new settings
            try:
                self._start_reader(*args)
                return
            except Exception:
                # Fall back to normal reset if start fails
                pass
        self._set_controls_enabled(True)
        try:
            self._file_menu.entryconfig(self._file_menu_connect_index, label="Connect")
        except Exception:
            pass

    # -- UI updates -------------------------------------------------------------
    def _post_result_with_records(
        self, message: str, records: Tuple[SAWLOG, ...] | None, *, success: bool
    ) -> None:
        self.root.after(0, lambda: self._update_ui_after_result_with_records(message, records, success))

    def _update_ui_after_result_with_records(
        self, message: str, records: Tuple[SAWLOG, ...] | None, success: bool
    ) -> None:
        self._set_busy(False)
        self._populate_overview(records)
        # Also refresh details window if open
        if self._detail_window is not None:
            try:
                self._detail_window.refresh()
            except Exception:
                pass

    def _set_busy(self, busy: bool) -> None:
        self._is_busy = busy
        # No button to disable; keep for future UI elements if needed
        _ = busy

    def _apply_status_state(self, state: str) -> None:
        self.status_var.set(state)
        color = {
            "Online": "#2da44e",
            "Offline": "#d73a49",
            "Unknown": "#6a737d",
        }.get(state, "#6a737d")
        try:
            self.status_indicator.configure(fg=color)
        except Exception:
            pass

    def _set_online(self, online: bool) -> None:
        self._apply_status_state("Online" if online else "Offline")

    def _post_online(self, online: bool) -> None:
        self.root.after(0, lambda: self._set_online(online))

    def _post_handle_disconnect(self, *, clear_table: bool) -> None:
        def task() -> None:
            self._set_online(False)
            if clear_table:
                self._clear_overview_rows()
        self.root.after(0, task)

    def _schedule_restart_with(self, settings: AppSettings) -> None:
        # If reader is running, schedule a restart with new settings
        if self._reader_thread and self._reader_thread.is_alive():
            try:
                config = PLCConfig(
                    address=settings.address.strip(),
                    rack=int(settings.rack),
                    slot=int(settings.slot),
                    tcp_port=int(settings.tcp_port),
                )
                self._pending_start = (config, int(settings.db), int(settings.start), int(settings.size), int(settings.interval_ms))
                # Stop current reader; cleanup will trigger restart
                self._stop_event.set()
            except Exception:
                # If parsing fails, ignore restart request
                self._pending_start = None

    def _console_log(self, line: str) -> None:
        import time as _time
        ts = _time.strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{ts}] {line}\n"
        def append() -> None:
            self.result_box.configure(state="normal")
            self.result_box.insert("end", entry)
            self.result_box.see("end")
            self.result_box.configure(state="disabled")
        self.root.after(0, append)

    def _post_notice(self, message: str, success: bool, *, duration_ms: int = 3000) -> None:
        prev = self.status_var.get()
        color = '#2da44e' if success else '#d73a49'
        def set_msg() -> None:
            try:
                self.status_text.configure(text=message)
                self.status_indicator.configure(fg=color)
            except Exception:
                pass
        def restore() -> None:
            try:
                self._apply_status_state(prev if prev in ('Online','Offline','Unknown') else 'Unknown')
                self.status_text.configure(text=self.status_var.get())
            except Exception:
                pass
        self.root.after(0, set_msg)
        self.root.after(duration_ms, restore)


    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for w in self._input_widgets:
            try:
                w.configure(state=state)
            except Exception:
                pass

    def _clear_overview_rows(self) -> None:
        if not hasattr(self, "tree"):
            return
        for item in self.tree.get_children():
            self.tree.delete(item)

    # -- Overview / details -----------------------------------------------------
    def _populate_overview(self, records: Tuple[SAWLOG, ...] | None) -> None:
        if not hasattr(self, "tree"):
            return

        # Remember current selection (by iid/index) and scroll offsets to restore after refresh
        try:
            current_sel = self.tree.selection()
            selected_iid = current_sel[0] if current_sel else None
            selected_index = int(selected_iid) if selected_iid is not None else None
            try:
                x0 = self.tree.xview()[0]
                y0 = self.tree.yview()[0]
            except Exception:
                x0 = 0.0
                y0 = 0.0
        except Exception:
            selected_iid = None
            selected_index = None
            x0 = 0.0
            y0 = 0.0

        # Rebuild rows
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._records_cache = tuple(records) if records else None
        if not records:
            return
        for index, record in enumerate(records):
            # Render flags with spaces; add double space between two groups of 8
            # Use full block for True (█) and light shade for False (░)
            _flag_glyphs = ["█" if flag else "░" for flag in record.flags]
            if len(_flag_glyphs) >= 16:
                flags_boxes = " ".join(_flag_glyphs[:8]) + "  " + " ".join(_flag_glyphs[8:16])
            else:
                flags_boxes = " ".join(_flag_glyphs)
            # Show 32 buttons as "order:count" pairs (decimal), interleaved in payload
            try:
                buttons_full = " ".join(
                    f"{int(record.buttons[2*i])}:{int(record.buttons[2*i+1])}" for i in range(32)
                )
            except Exception:
                buttons_full = ""
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
                    flags_boxes,
                    buttons_full,
                    timestamp,
                ),
            )

        # Restore selection and focus if possible
        try:
            if selected_index is not None:
                if 0 <= selected_index < len(records):
                    iid = str(selected_index)
                else:
                    iid = str(len(records) - 1)
                self.tree.selection_set(iid)
                self.tree.focus(iid)
                # Do not auto-scroll to keep scroll position
        except Exception:
            pass

        # Adjust columns to fit content for Flags and Buttons
        try:
            self._autosize_columns()
        except Exception:
            pass

        # Restore scroll positions (horizontal and vertical)
        try:
            self.tree.xview_moveto(x0)
            self.tree.yview_moveto(y0)
        except Exception:
            pass

    def _autosize_columns(self) -> None:
        import tkinter.font as tkfont
        if not hasattr(self, "tree"):
            return
        # Use the same monospaced font used by the Treeview style
        font = tkfont.Font(family="Consolas", size=10)
        padding = 24
        # Map column -> max width limits (pixels)
        max_limits = {"Flags": 400, "Buttons": 1200}
        for col in ("Flags", "Buttons"):
            # header width
            header_text = col
            max_w = font.measure(header_text)
            # content width
            for iid in self.tree.get_children(""):
                try:
                    value = str(self.tree.set(iid, col))
                except Exception:
                    value = ""
                if value:
                    w = font.measure(value)
                    if w > max_w:
                        max_w = w
            target = min(max_w + padding, max_limits.get(col, max_w + padding))
            self.tree.column(col, width=int(target))

    def _on_row_double_click(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection or self._records_cache is None:
            return
        try:
            index = int(selection[0])
        except ValueError:
            index = self.tree.index(selection[0])
        if 0 <= index < len(self._records_cache):
            # Close existing window if open
            if self._detail_window is not None:
                try:
                    self._detail_window.close()
                except Exception:
                    pass
                self._detail_window = None
            # Open new details window with data provider
            self._detail_window = DetailWindow(
                self.root,
                data_provider=lambda: self._records_cache,
                start_index=index,
                send_callback=self._send_record_to_plc,
                notice_callback=self._post_notice,
            )
            self._detail_window.focus()

    # -- send to PLC ------------------------------------------------------------
    def _send_record_to_plc(self, index: int, record: SAWLOG) -> None:
        # Run send in background to avoid blocking UI
        def worker() -> None:
            try:
                db = int(self.db_var.get())
                start = int(self.start_var.get())
                rack = int(self.rack_var.get())
                slot = int(self.slot_var.get())
                tcp_port = int(self.tcp_port_var.get())
                address = self.address_var.get().strip()
            except ValueError as exc:
                self._console_log(f"Invalid settings for send: {exc}")
                return
            config = PLCConfig(address=address, rack=rack, slot=slot, tcp_port=tcp_port)
            try:
                with PLCClient(config) as client:
                    client.write_sawlog_record(db, index, record, start=start)
                self._console_log(f"Sent record {index} to DB{db} @ {start + index * record.BYTE_SIZE}")
            except Exception as exc:
                self._console_log(f"Send failed: {exc}")

        threading.Thread(target=worker, daemon=True).start()

    # -- entrypoint -------------------------------------------------------------
    def run(self) -> None:
        self.root.mainloop()



