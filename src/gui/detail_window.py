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
    ) -> None:
        self._root = root
        self._data_provider = data_provider
        self._win: Optional[tk.Toplevel] = None
        self._content: Optional[ttk.Frame] = None
        self._index_var: Optional[tk.StringVar] = None
        self._header_font = None
        self._current_index = start_index
        # Cached widgets to avoid rebuild flicker
        self._header_value_labels: list[tk.Label] = []
        self._flags_cells: list[tk.Label] = []  # 16 cells
        self._buttons_cells: list[tk.Label] = []  # 64 cells
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
            self._render(idx)

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

        # dynamic content container
        content = ttk.Frame(win, padding=(8, 0))
        content.grid(row=1, column=0, sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
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

    def _render(self, index: int) -> None:
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
        # Ensure UI is built once; then only update text values to avoid flicker
        self._ensure_built()

        # Update header values (without index)
        values = [
            record.id,
            record.zone_id,
            record.sensor_id,
            record.length,
            record.drop_box_number,
            record.timestamp.to_datetime().isoformat(sep=" "),
        ]
        for lbl, val in zip(self._header_value_labels, values):
            lbl.configure(text=str(val))

        # Update flags
        for i in range(16):
            val = 1 if record.flags[i] else 0
            self._flags_cells[i].configure(text=str(val))

        # Update buttons
        for i in range(64):
            self._buttons_cells[i].configure(text=str(int(record.buttons[i])))

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
            val_label = tk.Label(header_frame, text="", anchor="w")
            val_label.grid(row=r, column=1, sticky="w", padx=6, pady=2)
            self._header_value_labels.append(val_label)
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
                cell = add_cell(flags_frame, "", r + 1, c + 1, width=3)
                self._flags_cells.append(cell)
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
                self._buttons_cells.append(cell)
        for c in range(9):
            buttons_frame.columnconfigure(c, weight=1)
        for r in range(9):
            buttons_frame.rowconfigure(r, weight=1)

        self._content.columnconfigure(0, weight=1)
        self._content.columnconfigure(1, weight=1)
        self._content.rowconfigure(1, weight=1)
