from __future__ import annotations

from typing import Callable, Optional

import tkinter as tk
from tkinter import ttk, messagebox

from .app_settings import AppSettings, save_settings


class SettingsWindow:
    """Modal settings window for PLC connection parameters.

    apply_callback receives the new AppSettings when Apply/Save is pressed.
    """

    def __init__(
        self,
        root: tk.Tk,
        initial: AppSettings,
        apply_callback: Callable[[AppSettings, bool], None],  # (settings, saved)
    ) -> None:
        self._root = root
        self._win: Optional[tk.Toplevel] = None
        self._apply_cb = apply_callback
        self._initial = initial
        self._build()

    def _build(self) -> None:
        win = tk.Toplevel(self._root)
        self._win = win
        win.title("Settings")
        win.transient(self._root)
        try:
            win.grab_set()
        except Exception:
            pass
        # Make window larger and resizable
        try:
            win.geometry("700x500")
        except Exception:
            pass

        # Root layout (two columns: tree on left, content on right)
        container = ttk.Frame(win, padding=12)
        container.grid(row=0, column=0, sticky="nsew")
        win.columnconfigure(0, weight=1)
        win.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=0)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(0, weight=1)

        # Variables
        self.address_var = tk.StringVar(value=self._initial.address)
        self.rack_var = tk.StringVar(value=str(self._initial.rack))
        self.slot_var = tk.StringVar(value=str(self._initial.slot))
        self.tcp_port_var = tk.StringVar(value=str(self._initial.tcp_port))
        self.db_var = tk.StringVar(value=str(self._initial.db))
        self.start_var = tk.StringVar(value=str(self._initial.start))
        self.size_var = tk.StringVar(value=str(self._initial.size))
        self.interval_var = tk.StringVar(value=str(self._initial.interval_ms))

        # Left tree navigation
        tree_frame = ttk.Frame(container)
        tree_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 12))
        self._tree = ttk.Treeview(tree_frame, show="tree", selectmode="browse", height=18)
        self._tree.pack(fill="y", expand=False)
        self._tree.insert("", "end", iid="PLC", text="PLC")
        self._tree.insert("", "end", iid="DB", text="DB")

        # Right content stack
        content_stack = ttk.Frame(container)
        content_stack.grid(row=0, column=1, sticky="nsew")
        content_stack.columnconfigure(0, weight=1)
        content_stack.rowconfigure(0, weight=1)

        plc_tab = ttk.Frame(content_stack)
        plc_tab.grid(row=0, column=0, sticky="nsew")

        db_tab = ttk.Frame(content_stack)
        db_tab.grid(row=0, column=0, sticky="nsew")

        self._content_frames = {"PLC": plc_tab, "DB": db_tab}

        # PLC fields
        plc_rows = [
            ("IP Address", self.address_var),
            ("Rack", self.rack_var),
            ("Slot", self.slot_var),
            ("TCP Port", self.tcp_port_var),
        ]
        for i, (label, var) in enumerate(plc_rows):
            ttk.Label(plc_tab, text=label).grid(row=i, column=0, sticky="w", pady=4, padx=(4, 8))
            ttk.Entry(plc_tab, textvariable=var, width=24).grid(row=i, column=1, sticky="ew", pady=4)
        plc_tab.columnconfigure(1, weight=1)

        # DB fields
        db_rows = [
            ("DB", self.db_var),
            ("Start Offset", self.start_var),
            ("Size (bytes)", self.size_var),
            ("Interval (ms)", self.interval_var),
        ]
        for i, (label, var) in enumerate(db_rows):
            ttk.Label(db_tab, text=label).grid(row=i, column=0, sticky="w", pady=4, padx=(4, 8))
            ttk.Entry(db_tab, textvariable=var, width=24).grid(row=i, column=1, sticky="ew", pady=4)
        db_tab.columnconfigure(1, weight=1)

        # Selection handling
        def on_tree_select(_event=None) -> None:
            sel = self._tree.selection()
            key = sel[0] if sel else "PLC"
            for name, frame in self._content_frames.items():
                frame.tkraise() if name == key else None
        self._tree.bind("<<TreeviewSelect>>", on_tree_select)
        # Default selection
        self._tree.selection_set("PLC")
        plc_tab.tkraise()

        # Buttons
        btns = ttk.Frame(container)
        btns.grid(row=1, column=0, columnspan=2, sticky="e", pady=(12, 0))
        ttk.Button(btns, text="Save", command=self._on_save).pack(side="right", padx=4)
        ttk.Button(btns, text="Apply", command=self._on_apply).pack(side="right", padx=4)
        ttk.Button(btns, text="Cancel", command=self._on_cancel).pack(side="right", padx=4)

        win.bind("<Escape>", lambda _e: self._on_cancel())

        # Center window over parent
        try:
            self._center_over_parent()
        except Exception:
            pass

    def _read_settings(self) -> AppSettings:
        try:
            return AppSettings(
                address=self.address_var.get().strip(),
                rack=int(self.rack_var.get()),
                slot=int(self.slot_var.get()),
                tcp_port=int(self.tcp_port_var.get()),
                db=int(self.db_var.get()),
                start=int(self.start_var.get()),
                size=int(self.size_var.get()),
                interval_ms=int(self.interval_var.get()),
            )
        except ValueError:
            messagebox.showerror(
                "Invalid settings",
                "Rack, Slot, TCP Port, DB, Start, Size, and Interval must be integers.",
                parent=self._win,
            )
            raise

    def _apply(self, save: bool) -> None:
        try:
            settings = self._read_settings()
        except Exception:
            return
        try:
            self._apply_cb(settings, save)
            if save:
                save_settings(settings)
        finally:
            # Close only on Save or Cancel; keep open on Apply
            if save:
                self._close()

    def _on_save(self) -> None:
        self._apply(True)

    def _on_apply(self) -> None:
        self._apply(False)

    def _on_cancel(self) -> None:
        self._close()

    def _close(self) -> None:
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
