# Repair Café tester receipt prototype (PT35)

Standalone PT35-side prototype; it does **not** modify the live Print Pet web app, systemd services, or its printer selection.

## Goal

Import the **last completed electrical safety test report** from an appliance tester, review the original measured values/result, and print a simple receipt using a spare Epson ESC/POS TCP printer.

The instrument's **make/model/firmware and communications interface are not yet known**, so there is deliberately **no invented USB/RS-232/Bluetooth protocol**. A future adapter must read the instrument's actual documented or verified protocol and produce the JSON format in `example_report.json`.

The report's `result` and `standard` fields must come from a confirmed source; this program does not infer PASS/FAIL or legal compliance. Demo data must not be presented as an actual safety test. The report includes the tester and operator for traceability; retain official records according to Repair Café procedures.

## Preview without wasting paper

```bash
python3 repair_cafe_tester/receipt.py --input repair_cafe_tester/example_report.json
```

## Optional test printing

Only after confirming the Epson's address and compatibility:

```bash
python3 repair_cafe_tester/receipt.py --input repair_cafe_tester/example_report.json \
  --print --printer-host 10.88.77.30
```

**Caution:** This sends ESC/POS binary over raw TCP/9100. It does not retry after a connection error; power-cycle the printer after a partial raster/command transfer. No integration with Print Pet's queue or recovery lock yet. It also uses a cutter command, so verify the connected printer supports it before test printing.

## Planned protocol adapter

1. Identify tester manufacturer, exact model, firmware, port type (USB, serial, Bluetooth, Ethernet, proprietary printer port).
2. Inspect manual for memory/result transfer commands, exported files, and any built-in printer protocol.
3. Collect one anonymized sample report or communication capture with permission (never connect to mains measurement terminals).
4. Write a read-only `adapters/<tester_model>.py` that returns the last **completed** result.
5. Add a PT35 UI button: **Read last test → Review → Print**, with duplicate-report confirmation.
6. Add Epson selection and actual status handling; protect incomplete print sessions.

This prototype is a receipt convenience tool, **not an electrical safety tester or compliance certification system**.
