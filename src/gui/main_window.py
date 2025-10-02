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
                # On final disconnect, always clear table
                self._post_handle_disconnect(clear_table=True)
                self._console_log("Disconnected")
                self.root.after(0, self._reset_controls_after_disconnect)

        self._reader_thread = threading.Thread(target=loop, daemon=True)
        self._reader_thread.start()

    def _reset_controls_after_disconnect(self) -> None:
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

        # Remember current selection (by iid/index) to restore after refresh
        try:
            current_sel = self.tree.selection()
            selected_iid = current_sel[0] if current_sel else None
            selected_index = int(selected_iid) if selected_iid is not None else None
        except Exception:
            selected_iid = None
            selected_index = None

        # Rebuild rows
        for item in self.tree.get_children():
            self.tree.delete(item)
        self._records_cache = tuple(records) if records else None
        if not records:
            return
        for index, record in enumerate(records):
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

        # Restore selection and focus if possible
        try:
            if selected_index is not None:
                if 0 <= selected_index < len(records):
                    iid = str(selected_index)
                else:
                    iid = str(len(records) - 1)
                self.tree.selection_set(iid)
                self.tree.focus(iid)
                self.tree.see(iid)
        except Exception:
            pass

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
                self.root, data_provider=lambda: self._records_cache, start_index=index
            )
            self._detail_window.focus()

    # -- entrypoint -------------------------------------------------------------
    def run(self) -> None:
        self.root.mainloop()
