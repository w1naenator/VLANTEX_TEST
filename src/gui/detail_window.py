from __future__ import annotations

from typing import Callable, Optional, Tuple

import tkinter as tk
from tkinter import ttk

from plc_client import SAWLOG


class DetailWindow:
    """Modal details window for a single SAWLOG with navigation.

    data_provider: callable that returns the latest tuple of SAWLOG records (or None).
    """

    def __init__(
        self,
        root: tk.Tk,
        data_provider: Callable[[], Tuple[SAWLOG, ...] | None],
        start_index: int = 0,
        send_callback: Callable[[int, SAWLOG], None] | None = None,
        notice_callback: Callable[[str, bool], None] | None = None,
    ) -> None:
        self._root = root
        self._data_provider = data_provider
        self._send_cb = send_callback
        self._notice_cb = notice_callback
        self._win: Optional[tk.Toplevel] = None
        self._content: Optional[ttk.Frame] = None
        self._index_var: Optional[tk.StringVar] = None
        self._header_font = None
        self._current_index = start_index
        # Cached widgets to avoid rebuild flicker
        self._header_value_labels: list[tk.Label] = []
        self._flags_cells: list[tk.Label] = []  # 16 cells (hidden in view/edit unified mode)
        self._buttons_cells: list[tk.Label] = []  # 64 cells (hidden in view/edit unified mode)
        # Unified editors used for both view/edit (disabled in view mode)
        self._header_edit_entries: list[tk.Entry] = []
        self._flag_check_vars: list[tk.BooleanVar] = []
        self._flag_checkbuttons: list[tk.Checkbutton] = []
        self._button_edit_entries: list[tk.Entry] = []
        self._edit_mode: bool = False
        self._open()

    # -- public API -------------------------------------------------------------
    def focus(self) -> None:
        if self._win is not None:
            self._win.focus_set()

    def close(self) -> None:
        if self._win is not None:
            try:
                self._win.grab_release()
            except Exception:
                pass
            try:
                self._win.destroy()
            except Exception:
                pass
            self._win = None

    def refresh(self) -> None:
        """Re-render current record using latest data from the provider."""
        self._render(self._current_index)

    # -- internals --------------------------------------------------------------
    def _open(self) -> None:
        if self._win is not None and self._win.winfo_exists():
            self.close()

        win = tk.Toplevel(self._root)
        self._win = win
        win.transient(self._root)
        try:
            win.grab_set()  # modal: lock main window interactions
        except Exception:
            pass

        # nav bar
        nav = ttk.Frame(win, padding=(8, 8))
        nav.grid(row=0, column=0, sticky="ew")
        nav.columnconfigure(1, weight=1)

        idx_var = tk.StringVar(value=str(self._current_index))
        self._index_var = idx_var

        def data_count() -> int:
            recs = self._data_provider() or ()
            return len(recs)

        def goto(idx: int) -> None:
            count = data_count()
            if count <= 0:
                return
            idx = max(0, min(idx, count - 1))
            self._current_index = idx
            idx_var.set(str(idx))
            # Force content refresh even in edit mode
            self._render(idx, force=True)

        ttk.Button(nav, text="◀ Previous", command=lambda: goto(self._current_index - 1)).grid(
            row=0, column=0, sticky="w"
        )
        entry = ttk.Entry(nav, textvariable=idx_var, width=8)
        entry.grid(row=0, column=1, sticky="ew", padx=8)
        entry.bind("<Return>", lambda _e: goto(int(idx_var.get() or 0)))
        self._total_label = ttk.Label(nav, text="")
        self._total_label.grid(row=0, column=2, sticky="w")
        ttk.Button(nav, text="Next ▶", command=lambda: goto(self._current_index + 1)).grid(
            row=0, column=3, sticky="e"
        )

        # Edit toggle button
        self._edit_btn = ttk.Button(nav, text="Edit", command=self._toggle_edit)
        self._edit_btn.grid(row=0, column=4, sticky="e", padx=(8, 0))
        # Send button (enabled only in edit mode if callback is provided)
        self._send_btn = ttk.Button(nav, text="Send to PLC", command=self._do_send)
        self._send_btn.grid(row=0, column=5, sticky="e", padx=(8, 0))
        if self._send_cb is None:
            self._send_btn.state(["disabled"])  # disable when no callback
        else:
            # Start disabled until Edit mode is enabled
            self._send_btn.state(["disabled"])  # enabled only in edit mode

        # dynamic content container
        content = ttk.Frame(win, padding=(8, 0))
        content.grid(row=1, column=0, sticky="nsew")
        # status bar at bottom
        status_bar = ttk.Frame(win, padding=(8, 4))
        status_bar.grid(row=2, column=0, sticky="ew")
        self._status_var = tk.StringVar(value="")
        self._status_label = ttk.Label(status_bar, textvariable=self._status_var)
        self._status_label.pack(side="left")

        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        win.rowconfigure(2, weight=0)
        self._content = content

        def on_close() -> None:
            self.close()

        win.protocol("WM_DELETE_WINDOW", on_close)

        self._render(self._current_index)
        # Center window over parent
        try:
            self._center_over_parent()
        except Exception:
            pass
        win.focus_set()

    def _center_over_parent(self) -> None:
        if self._win is None:
            return
        parent = self._root
        self._win.update_idletasks()
        pw = parent.winfo_width() or parent.winfo_reqwidth()
        ph = parent.winfo_height() or parent.winfo_reqheight()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        ww = self._win.winfo_width()
        wh = self._win.winfo_height()
        x = px + max(0, (pw - ww) // 2)
        y = py + max(0, (ph - wh) // 2)
        self._win.geometry(f"+{x}+{y}")

    def _render(self, index: int, *, force: bool = False) -> None:
        if self._content is None or self._win is None:
            return
        records = self._data_provider() or ()
        count = len(records)
        # update title/total label
        if count > 0:
            self._win.title(f"SAWLOG [{index}/{count - 1}] Details")
            self._total_label.configure(text=f"of {count - 1}")
        else:
            self._win.title("SAWLOG Details")
            self._total_label.configure(text="of 0")

        if not (0 <= index < count):
            return
        record = records[index]
        # Ensure UI is built once; then only update values in view mode
        self._ensure_built()

        # If currently editing, do not overwrite user-edited values unless forced
        if self._edit_mode and not force:
            return

        # Update header entry values (without index)
        values = [
            record.id,
            record.zone_id,
            record.sensor_id,
            record.length,
            record.drop_box_number,
            record.timestamp.to_datetime().isoformat(sep=" "),
        ]
        for ent, val in zip(self._header_edit_entries, values):
            try:
                ent.configure(state="normal")
                ent.delete(0, tk.END)
                ent.insert(0, str(val))
                # Keep editable if currently in edit mode
                if not self._edit_mode:
                    ent.configure(state="disabled")
            except Exception:
                pass

        # Update flags (checkbox variables)
        for i in range(16):
            try:
                self._flag_check_vars[i].set(bool(record.flags[i]))
            except Exception:
                pass

        # Update buttons (entries)
        for i in range(64):
            try:
                ent = self._button_edit_entries[i]
                ent.configure(state="normal")
                ent.delete(0, tk.END)
                ent.insert(0, str(int(record.buttons[i])))
                if not self._edit_mode:
                    ent.configure(state="disabled")
            except Exception:
                pass

    def _ensure_built(self) -> None:
        if self._content is None or self._win is None:
            return
        if self._header_value_labels and self._flags_cells and self._buttons_cells:
            return

        # Fonts for table headers
        if self._header_font is None:
            import tkinter.font as tkfont
            base = tkfont.nametofont("TkDefaultFont")
            self._header_font = base.copy()
            self._header_font.configure(weight="bold")

        def add_cell(parent, text, row, col, *, header=False, width=3) -> tk.Label:
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
                lbl.configure(font=self._header_font)
            lbl.grid(row=row, column=col, sticky="nsew")
            return lbl

        # Header
        header_frame = ttk.LabelFrame(self._content, text="Header")
        header_frame.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=0, pady=8)
        header_labels = ["ID", "Zone", "Sensor", "Length", "DropBox", "Timestamp"]
        for r, label in enumerate(header_labels):
            ttk.Label(header_frame, text=f"{label}:").grid(row=r, column=0, sticky="w", padx=6, pady=2)
            # Keep label element for legacy but hide it; use entry for both view/edit
            val_label = tk.Label(header_frame, text="", anchor="w")
            val_label.grid(row=r, column=1, sticky="w", padx=6, pady=2)
            val_label.grid_remove()
            self._header_value_labels.append(val_label)
            # Unified entry (disabled in view mode)
            e = tk.Entry(header_frame)
            e.grid(row=r, column=1, sticky="ew", padx=6, pady=2)
            e.configure(state="disabled")
            self._header_edit_entries.append(e)
        header_frame.columnconfigure(1, weight=1)

        # Flags grid
        flags_frame = ttk.LabelFrame(self._content, text="Flags (FL0..FL15)")
        flags_frame.grid(row=1, column=0, sticky="nsew", padx=0, pady=8)
        add_cell(flags_frame, "", 0, 0, header=True, width=3)
        for c in range(8):
            add_cell(flags_frame, c, 0, c + 1, header=True, width=3)
        for r in range(2):
            add_cell(flags_frame, r * 8, r + 1, 0, header=True, width=3)
            for c in range(8):
                # Keep legacy cell hidden; use checkbox for view/edit
                cell = add_cell(flags_frame, "", r + 1, c + 1, width=3)
                cell.grid_remove()
                self._flags_cells.append(cell)
                var = tk.BooleanVar(value=False)
                chk = tk.Checkbutton(flags_frame, variable=var, text="", width=2)
                chk.grid(row=r + 1, column=c + 1)
                chk.configure(state="disabled")
                self._flag_check_vars.append(var)
                self._flag_checkbuttons.append(chk)
        for c in range(9):
            flags_frame.columnconfigure(c, weight=1)
        for r in range(3):
            flags_frame.rowconfigure(r, weight=1)

        # Buttons grid
        buttons_frame = ttk.LabelFrame(self._content, text="Buttons (BT0..BT63)")
        buttons_frame.grid(row=1, column=1, sticky="nsew", padx=8, pady=8)
        add_cell(buttons_frame, "", 0, 0, header=True, width=3)
        for c in range(8):
            add_cell(buttons_frame, c, 0, c + 1, header=True, width=3)
        for r in range(8):
            add_cell(buttons_frame, r * 8, r + 1, 0, header=True, width=3)
            for c in range(8):
                cell = add_cell(buttons_frame, "", r + 1, c + 1, width=3)
                cell.grid_remove()
                self._buttons_cells.append(cell)
                ent = tk.Entry(buttons_frame, width=3)
                ent.grid(row=r + 1, column=c + 1)
                ent.configure(state="disabled")
                self._button_edit_entries.append(ent)
        for c in range(9):
            buttons_frame.columnconfigure(c, weight=1)
        for r in range(9):
            buttons_frame.rowconfigure(r, weight=1)

        self._content.columnconfigure(0, weight=1)
        self._content.columnconfigure(1, weight=1)
        self._content.rowconfigure(1, weight=1)

    def _toggle_edit(self) -> None:
        self._ensure_built()
        self._edit_mode = not self._edit_mode
        editing = self._edit_mode
        try:
            self._edit_btn.configure(text="View" if editing else "Edit")
        except Exception:
            pass
        # Enable/disable send button when editing
        try:
            if self._send_cb is None:
                self._send_btn.state(["disabled"])  # no callback available
            else:
                if editing:
                    self._send_btn.state(["!disabled"])  # enable
                else:
                    self._send_btn.state(["disabled"])  # disable in view mode
        except Exception:
            pass

        # Toggle header entries enabled/disabled
        for ent in self._header_edit_entries:
            try:
                ent.configure(state=("normal" if editing else "disabled"))
            except Exception:
                pass

        # Toggle flags checkbuttons enabled/disabled
        for chk in self._flag_checkbuttons:
            try:
                chk.configure(state=("normal" if editing else "disabled"))
            except Exception:
                pass

        # Toggle buttons entries enabled/disabled
        for ent in self._button_edit_entries:
            try:
                ent.configure(state=("normal" if editing else "disabled"))
            except Exception:
                pass

    def _do_send(self) -> None:
        if not self._edit_mode or self._send_cb is None:
            return
        # Build SAWLOG from editor fields
        try:
            id_val = int(self._header_edit_entries[0].get())
            zone_val = int(self._header_edit_entries[1].get()) & 0xFF
            sensor_val = int(self._header_edit_entries[2].get()) & 0xFF
            length_val = int(self._header_edit_entries[3].get()) & 0xFFFF
            dropbox_val = int(self._header_edit_entries[4].get()) & 0xFFFF
        except Exception:
            tk.messagebox.showerror("Invalid input", "Header fields must be numbers.", parent=self._win)
            return

        flags = tuple(bool(var.get()) for var in self._flag_check_vars)
        buttons = []
        for ent in self._button_edit_entries:
            try:
                v = int(ent.get(), 0)
            except Exception:
                v = 0
            v = max(0, min(v, 15))
            buttons.append(v)
        buttons_t = tuple(buttons)

        # Timestamp: keep previous value from provider (no direct editing of timestamp for simplicity)
        recs = self._data_provider() or ()
        if not (0 <= self._current_index < len(recs)):
            return
        ts = recs[self._current_index].timestamp

        try:
            new_record = SAWLOG(
                id=id_val,
                zone_id=zone_val,
                sensor_id=sensor_val,
                length=length_val,
                drop_box_number=dropbox_val,
                flags=flags,
                buttons=buttons_t,
                timestamp=ts,
            )
        except Exception as exc:
            tk.messagebox.showerror("Invalid data", str(exc), parent=self._win)
            return

        try:
            self._send_cb(self._current_index, new_record)
        except Exception as exc:
            self._set_status(f"Send failed: {exc}", success=False)
            if self._notice_cb:
                self._notice_cb(f"Send failed: {exc}", False)
            return
        self._set_status("Record sent to PLC.", success=True)
        if self._notice_cb:
            self._notice_cb("Record sent to PLC.", True)

    def _set_status(self, message: str, *, success: bool, duration_ms: int = 3000) -> None:
        color = "#2da44e" if success else "#d73a49"
        try:
            self._status_label.configure(foreground=color)
        except Exception:
            pass
        self._status_var.set(message)
        if self._win is not None:
            def clear() -> None:
                self._status_var.set("")
                try:
                    self._status_label.configure(foreground="")
                except Exception:
                    pass
            self._win.after(duration_ms, clear)


