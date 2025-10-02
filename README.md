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
    └── plc_client          # Reusable PLC client package
        ├── __init__.py
        ├── client.py       # High-level snap7 client wrapper
        ├── config.py       # PLC connection config
        └── datatypes.py    # DTL, SAWLOG, SawlogsRegisterDB types
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

   Enter the PLC connection parameters and click **Read Data**. The defaults target
   `DB200` and request the full SAWLOG register (`SawlogsRegisterDB`, 255 records /
   14 280 bytes). The UI shows a hex preview and a parsed overview table.

4. Or run a one-off read from the CLI:

   ```powershell
   python src/main.py 192.168.61.110 200 0 14280 --rack 0 --slot 1
   ```

   When the requested range covers the full register (offset `0`, length `14280`), the
   client reads into `SawlogsRegisterDB` so you can iterate over typed `SAWLOG`
   instances.

## VS Code launchers

Open the Run and Debug panel and pick one of the included launch configurations:

- Python: Debug GUI (main.py)
- Python: Release GUI (main.py)
- Python: Debug CLI – Full Register (DB200, 14280 bytes)
- Python: Release CLI – Full Register

You can change the target IP via the `PLC_ADDRESS` environment variable in
`.vscode/launch.json`.

## GUI overview

- Two tabs: “Overview” (default) and “Text”.
- Overview shows a table of parsed records with columns: Index, ID, Zone, Sensor,
  Length, DropBox, Flags (hex), Buttons (preview), Timestamp. Double‑click any row to
  open a detail dialog.
- Detail dialog presents:
  - Header fields (ID, Zone, Sensor, Length, DropBox, Timestamp)
  - Flags table (FL0..FL15) as a bordered grid with highlighted row/column headers
    (rows 0 and 8; columns 0..7)
  - Buttons table (BT0..BT63) as a bordered 8×8 grid with highlighted headers
    (rows 0,8,16,24,32,40,48,56; columns 0..7)
- Initial window width is doubled for better visibility.

## Notes

- The defaults (`rack=0`, `slot=1`) match many S7-1200/1500/ET‑200SP CPUs. Adjust as
  needed (e.g., some devices use slot 2).
- `plc_client.datatypes.DTL` models the Siemens Date-and-Time structure (12 bytes) and
  converts to Python `datetime`.
- `plc_client.datatypes.SAWLOG` captures a record: header fields, 16 packed flags,
  64 nibble‑sized button values, and an embedded `DTL` timestamp. Size: 56 bytes.
- `plc_client.datatypes.SawlogsRegisterDB` represents the 255‑entry register (DB200).
- The code focuses on reading; writing can be added by extending `PLCClient` with
  snap7 write calls (`db_write`, `write_area`, etc.).
- PLC must allow PUT/GET and the data block should be non‑optimized (standard
  compatible) for absolute DB access.
