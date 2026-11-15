# Test plan — solar-inverter-testing

Structure follows ISO/IEC/IEEE 29119-3 (test plan), kept short.

## 1. Context

| Item           | Value                                                                                                        |
| -------------- | ------------------------------------------------------------------------------------------------------------ |
| Test item      | `inverter_lab` 1.0.0: a simulated single-phase 5 kW PV inverter with Modbus RTU and Modbus TCP interfaces     |
| Basis          | MODBUS Application Protocol V1.1b3; MODBUS over Serial Line V1.02; MODBUS Messaging on TCP/IP V1.0b; SunSpec Device Information Model and models 1, 101, 120, 123; the datasheet of the simulator (`tests/support/datasheet.py`) |
| Out of scope   | Reactive power and power factor controls, three-phase models, SunSpec models 7xx (IEEE 1547-2018), TLS, real inverter hardware |
| Stakeholders   | Readers of the portfolio: hiring managers, test leads, and people with no technical background               |

## 2. Risks and what covers them

| Risk                                                                    | Covered by                                         |
| ----------------------------------------------------------------------- | -------------------------------------------------- |
| A damaged frame is obeyed or believed                                   | `test_crc`, `test_protocol_rtu`, `test_client_noise`, `test_robustness` |
| The device answers when it must stay silent (foreign address, broadcast) | `test_protocol_rtu`, `test_protocol_tcp`           |
| The register map differs from the SunSpec standard                      | `test_sunspec_map` against the official model JSON, `test_interop_sunspec` |
| Only the project's own client can talk to the device                    | `test_interop_pymodbus`, `test_interop_sunspec`    |
| The inverter feeds in while the grid is down, or reconnects too early   | `test_grid_safety`                                 |
| The inverter runs past its temperature limit                            | `test_grid_safety` (boundary 94.9 / 95.0 and 75.1 / 75.0 °C) |
| A power limit is ignored, overshoots, or never expires                  | `test_power_limit`                                 |
| A refused write changes part of the state                               | `test_register_access`                             |
| Wrong power, energy or scaling in the registers                         | `test_inverter_day`, `test_sunspec_codec`          |
| The suite passes whatever the code does                                 | `scripts/mutants.py`: 38 planted bugs              |
| The visual page shows something the simulator does not do               | `site/test/twin.test.mjs`, `test_pages`            |

## 3. Approach

- **Levels.** Unit tests of the codecs; device tests through the bus on three links; interoperability with two
  third-party clients; hardware-in-the-loop on a real RS-485 line.
- **Links.** `LINK=memory` (socket pair), `LINK=socat` (two virtual serial ports), `LINK=tcp`,
  `LINK=serial://PORT` (bench). One suite; markers skip a test where it does not apply.
- **Techniques.** Specification examples, equivalence classes and boundary values for every writable point,
  state transitions of the inverter (sleeping, starting, MPPT, throttled, fault, standby), property-based tests
  with Hypothesis for frames, reads, writes and noise, an independent oracle for the datasheet.
- **Determinism.** Simulated time moves only on command. No test sleeps to wait for the inverter.
- **Evidence.** Every frame of every test is recorded to `evidence/run-<link>.json` and shown on the visual page.

## 4. Entry and exit criteria

- Entry: lint, format and type checks pass.
- Exit: all tests pass on the three CI links; the mutation check catches every planted bug and its control run
  passes; the JavaScript twin answers like the Python simulator; the browser tests pass.

## 5. Environment

GitHub Actions `ubuntu-latest`, Python 3.12, socat, Node.js 24, Chromium from Playwright. Bench: two USB-RS485
adapters on one computer, see `bench/README.md`.

## 6. Deliverables

Allure report, the visual page, the mutation table, this plan and the test report.
