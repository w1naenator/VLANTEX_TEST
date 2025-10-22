# Siemens S7-200SP PLC Reader

A minimal Python tool that connects to a Siemens S7-200SP PLC using
[`python-snap7`](https://github.com/gijzelaerr/python-snap7) to read raw bytes from
data blocks, inputs, or outputs. It can interpret the S7 `DTL` structure, individual
`SAWLOG` records, and the full 255-record SAWLOG register (DB200).

## Project structure

```
.
├── requirements.txt        # Third-party dependencies
├── .vscode                 # VS Code launchers (Debug/Release)
│   ├── launch.json
│   └── extensions.json
└── src
    ├── main.py             # Entry point: GUI (default) and CLI
    ├── gui                 # GUI modules
    │   ├── main_window.py  # Main window (overview, console, connect)
    │   ├── detail_window.py# Record details, edit + send to PLC
    │   ├── settings_window.py # Settings (PLC + DB) tree view
    │   └── app_settings.py # settings.json load/save (next to launcher)
    └── plc_client          # Reusable PLC client package
        ├── __init__.py
        ├── client.py       # High-level snap7 client wrapper (read/write)
        ├── config.py       # PLC connection config
        ├── datatypes.py    # DTL, SAWLOG, SawlogsRegisterDB types
        └── readers.py      # Shared helpers to read/parse buffers
```

## Getting started

1. Create and activate a virtual environment (optional but recommended):

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

2. Install the dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

3. Launch the GUI tool and read from your PLC:

   ```powershell
   python src/main.py
   ```

   The GUI opens at 1920×1080 with a status toolbar. Use:
   - File → Settings… to configure PLC (IP, rack, slot, TCP port) and DB (DB, start, size, interval). Settings are saved to `settings.json` next to the launcher.
   - File → Connect or double‑click the status label to connect/disconnect. Disconnect asks for confirmation.
   - When connected, the app reads cyclically with retry/backoff; last data stays visible during retry.

4. Or run a one-off read from the CLI:

   ```powershell
   python src/main.py 192.168.61.110 200 0 23970 --rack 0 --slot 1
   ```

   When the requested range covers the full register (offset `0`, length `23970`), the
   client reads into `SawlogsRegisterDB` so you can iterate over typed `SAWLOG`
   instances.

## VS Code launchers

Open the Run and Debug panel and pick one of the included launch configurations:

- Python: Debug GUI (main.py)
- Python: Release GUI (main.py)
- Python: Debug CLI – Full Register (DB200, 23970 bytes)
- Python: Release CLI – Full Register

You can change the target IP via the `PLC_ADDRESS` environment variable in
`.vscode/launch.json`.

## GUI overview

- Two tabs: “Overview” (default) and “Console”.
- Overview table columns: Index, ID, Zone, Sensor, Length, Position, DropBox, Flags, Buttons, Timestamp.
  - Flags render as blocks (█/░) with a double space between four groups of eight.
  - Buttons shows 32 pairs as "order,count" (decimal), space‑separated.
  - Table preserves selection and scroll positions on refresh; columns autosize to content.
  - Double‑click a row to open the Details window.
- Details window (centered, modal):
  - Unified fields for view/edit; in view mode inputs are disabled (greyed), Edit enables them.
  - Flags are checkboxes; buttons are numeric fields (0–255).
  - Navigation (Previous/Next/jump index). In Edit mode, changing index updates fields and keeps them editable.
  - “Send to PLC” writes the edited record back to the PLC; a local status bar shows send results; the main status bar also shows a transient notice.

## Notes

- The defaults (`rack=0`, `slot=1`) match many S7-1200/1500/ET‑200SP CPUs. Adjust as
  needed (e.g., some devices use slot 2).
- `plc_client.datatypes.DTL` models the Siemens Date-and-Time structure (12 bytes) and
  converts to Python `datetime`.
- `plc_client.datatypes.SAWLOG` captures a record: header fields (including `position` and 8‑bit `sensor_id`), 32 packed flags (two words),
  32 buttons as Byte[2][32] (first 32 then 32, e.g. orders followed by counts), and an embedded `DTL` timestamp. Size: 94 bytes.
- `plc_client.datatypes.SawlogsRegisterDB` represents the 255‑entry register (DB200).
- Writing one SAWLOG is implemented (`PLCClient.write_db`, `write_sawlog_record`); ensure DB layout matches the SAWLOG struct (94 bytes, non‑optimized).
- PLC must allow PUT/GET and the data block should be non‑optimized (standard
  compatible) for absolute DB access.

## Usage quick guide

- Configure PLC/DB: File → Settings… (tree on left: PLC, DB). Apply or Save makes changes effective immediately (auto‑restart reader without clearing the table).
- Connect/Disconnect: File → Connect or double‑click the status label. Disconnect shows a confirmation and clears the table.
- Inspect data: Overview tab formats flags and all button values; use horizontal scroll if needed.
- Edit/sync a record: Double‑click a row → Edit → change fields → Send to PLC. Watch the detail window status bar for success/failure.

## Build Windows EXE

The project packages cleanly with PyInstaller (tested on Windows 11).

- Prerequisites: Python 3.11+ and an internet connection.
- Output: `dist/PLCReader/PLCReader.exe` (GUI by default; CLI when arguments are provided).

Steps (PowerShell):

1) Create/activate a venv and install deps + PyInstaller

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   pip install -r requirements.txt pyinstaller
   ```

2) Generate a spec (includes snap7 DLLs and `settings.json`)

   ```powershell
   pyi-makespec --name PLCReader --paths src \`
                --add-data "src\settings.json;." \`
                --collect-binaries snap7 \`
                --console src\main.py
   ```

3) Build

   ```powershell
   pyinstaller --clean PLCReader.spec
   ```

4) Place `settings.json` next to the EXE (PyInstaller 6.x puts data under `_internal` by default)

   ```powershell
   Copy-Item src\settings.json dist\PLCReader\settings.json -Force
   ```

Run the app:

- GUI: `dist\PLCReader\PLCReader.exe`
- CLI example (expects a reachable PLC):

  ```powershell
  dist\PLCReader\PLCReader.exe 192.168.61.110 200 0 23970 --rack 0 --slot 1 --tcp-port 102
  ```

Notes:

- The build bundles the `snap7` runtime DLL so no extra runtime install is needed.
- `settings.json` is looked up next to the launcher (EXE); if missing, defaults are used and the file is created on save from the Settings window.

