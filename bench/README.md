# The bench: the same tests over a real RS-485 line

Two USB-RS485 adapters on one computer. The simulator answers on the first, the tests ask through the second, and
between them is a real twisted pair with real voltages, echo and timing.

## Wiring

```text
adapter 1 (simulator)        adapter 2 (tests)
        A  ───────────────────  A
        B  ───────────────────  B
      GND  ───────────────────  GND   (if the adapters have the terminal)
```

- A to A, B to B. If nothing answers, swap the two wires on one side: some adapters label them the other way round.
- For a line longer than a few metres put a 120 Ω resistor between A and B at each end.
- Find the ports: `ls /dev/ttyUSB*` on Linux, Device Manager → Ports on Windows (`COM5`, `COM6`).

## Run

```bash
# terminal 1: the inverter
python -m inverter_lab serve --serial /dev/ttyUSB0 --baud 9600

# terminal 2: the tests
LINK="serial:///dev/ttyUSB1?baud=9600" pytest -m "not pages"

# or just watch it
python -m inverter_lab watch "serial:///dev/ttyUSB1?baud=9600"
```

On Windows use `--serial COM5` and `LINK="serial://COM6?baud=9600"`.

Before the first test the suite reads register 100. If it does not hold the simulator marker `0x51A1`, the run
stops: the tests change the clock and the grid state, and they refuse to do that to a real inverter.

## What differs from the cloud run

| | In CI | On the bench |
| --- | --- | --- |
| `test_bench.py` (3 tests) | skipped | runs: 1000 polls without a lost frame, round-trip time, a 255-byte answer |
| Tests marked `internal` | run | skipped: they read the simulator's memory |
| Speed | about 40 s | a few minutes at 9600 baud |

## Not in version 1.0

ESP32 firmware that answers on the line instead of the Python simulator. It needs MAX3485 transceiver modules,
which are not on the bench yet, and firmware that cannot be tested is not published.
