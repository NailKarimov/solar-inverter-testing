# Test summary report — solar-inverter-testing

Structure follows ISO/IEC/IEEE 29119-3 (test completion report). Numbers are from the run of 15 November 2026.

## 1. Summary

| Item         | Value                                                                                  |
| ------------ | -------------------------------------------------------------------------------------- |
| Date         | 2026-11-15                                                                             |
| Test item    | `inverter_lab` 1.0.0                                                                   |
| Environment  | Linux, Python 3.13, socat, Node.js 22, Chromium (Playwright)                           |
| Result       | 359 tests on three links: 752 passes, 0 failures; 18 browser tests passed              |
| Test quality | 38/38 planted bugs caught, control runs passed; twin: 2572/2572 answers identical      |
| Open defects | none                                                                                   |
| Not run      | 3 bench tests (`test_bench.py`): they need two USB-RS485 adapters                      |

## 2. Results by link

| Link                       | Passed | Skipped | Failed | Time  |
| -------------------------- | ------ | ------- | ------ | ----- |
| `memory` (socket pair)     | 309    | 50      | 0      | 40 s  |
| `socat` (virtual serial)   | 243    | 116     | 0      | 31 s  |
| `tcp` (Modbus TCP)         | 200    | 159     | 0      | 15 s  |
| Browser tests of the page  | 18     | 0       | 0      | 15 s  |

A skip is by design: unit tests run once (in memory), serial framing tests do not run on TCP, TCP tests do not run
on serial links, third-party clients need a real port, bench tests need the bench.

## 3. Findings

The system under test is the project's own simulator, so a fault found by a test is fixed, not reported as an
open defect. Found and fixed while the suite was written:

| Id    | Found by                                    | What was wrong                                                                                                  | Fix                                                             |
| ----- | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| SIT-1 | comparison with the official SunSpec client | Scale factors were applied as `raw * 10.0 ** sf`; 2137 with factor -2 gave 21.370000000000001, not 21.37        | negative factors divide by an exact power of ten                |
| SIT-2 | review before the JavaScript twin was written | Python's `round()` rounds halves to even, so register values could differ by one count from the datasheet rule  | one `round_half_up()` used for every register                   |
| SIT-3 | `test_interop_sunspec`                      | The project's reader reported padding registers as "no value" while the official client reports 32768           | padding is excluded from the comparison: it is not a value      |
| SIT-4 | the live page                               | Mutant M20 was described as "delivers more power than its rating", but the limit path still capped the output; the real effect is a false THROTTLED state | the description of M20 corrected; the mutant itself is unchanged |

SIT-4 is a fault in the test documentation, found because the live check "never more than 5000 W" stayed green
with the bug switched on.

## 4. Mutation check

38 planted bugs in six areas (wire, register map, sun and power, safety, commands, client), each run against the
whole suite; every one failed at least one test. The table: [`mutants-result.md`](../mutants-result.md).
Nine mutants are caught by exactly one test (M05, M07, M11, M14, M25, M26, M27, M37, M38): that test is the only
guard of its rule and must not be weakened.

## 5. Deviations from the plan

- ESP32 firmware for the bench is not part of 1.0: MAX3485 modules are not available yet.
- The bench tests have not been run yet; the adapters are available, the run is planned.
- The local run used Python 3.13 and Node.js 22; CI uses 3.12 and 24.

## 6. Recommendations

1. Run the suite on the bench and add the numbers to this report.
2. Add SunSpec models 701 to 705 (IEEE 1547-2018 controls) when the next stage of the plan starts.
3. Point the read-only tests (map, identity, interoperability) at a real SunSpec inverter.
