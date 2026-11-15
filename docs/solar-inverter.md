# Guide: testing a solar inverter over Modbus and SunSpec

The same content as an interactive page with five views, in English and Russian:
[solar-inverter.html](https://nailkarimov.github.io/solar-inverter-testing/solar-inverter.html).

## What this is and why

A grid-tied solar inverter is a small computer that other computers talk to: monitoring portals, home energy
managers, the grid operator. They read power and energy, and they send commands such as "limit your output to
50 %". Since the 2010s this conversation mostly runs over **Modbus**, with the **SunSpec** register map on top so
that equipment from different makers understands each other.

A tester in this field needs to show three things: that the device speaks the protocol correctly, that its
numbers mean what the standard says, and that its safety functions work. This repository does that against a
simulator, because a simulator can run in CI, can be broken on purpose, and can be shown to anyone in a browser.

## Modbus in one page

- A **client** (master) asks, a **server** (the inverter) answers. The server never speaks first.
- The data are 16-bit **registers** with numeric addresses.
- A message is a **function code** and its data. This project uses four: `03` and `04` read registers, `06` writes
  one, `16` (`0x10`) writes several.
- A refusal is an **exception response**: the function code plus `0x80`, then a reason. `01` unknown function,
  `02` no such address, `03` value not allowed.

On a serial line (**Modbus RTU**, usually RS-485) a frame is:

```text
01          03        9C 94        00 01       EB B6
address     function  register     count       CRC-16, low byte first
```

Up to 247 devices share one pair of wires, so every frame starts with an address. Address 0 is a broadcast: every
device carries out a write and none answers. A frame with a wrong CRC is dropped without an answer.

On a network (**Modbus TCP**) the address and the CRC are replaced by a 7-byte MBAP header:

```text
00 01            00 00         00 06       01     03 9C 94 00 01
transaction id   protocol 0    length      unit   the same message
```

## SunSpec in one page

- The map starts at register 40000 with the marker `SunS` (`0x5375 0x6E53`).
- After it comes a chain of **models**. Each begins with its id and its length, so a client can walk the chain
  without knowing the device. The chain ends with id `0xFFFF`.
- This simulator has model 1 (who am I), 101 (single-phase inverter measurements), 120 (nameplate ratings) and 123
  (immediate controls: connect, power limit).
- A value is an integer plus a **scale factor** stored in another register: 2340 with factor -1 is 234.0 V.
- A value the device does not have reads as a fixed "not implemented" pattern (`0xFFFF` for uint16, `0x8000` for
  int16), never as zero.

## The simulator

`src/inverter_lab/inverter.py` is a physical model of a 5 kW inverter with a 6 kWp array on a clear June day in
Riga. It moves in one-second ticks and only on command.

| Behaviour            | Rule                                                                                 |
| -------------------- | ------------------------------------------------------------------------------------ |
| Sun                  | DC power is a bell between 04:30 and 22:15; full cloud cover leaves a quarter         |
| Conversion           | AC = DC × 0.975 − 20 W, clipped at 5000 W                                             |
| Start-up             | 60 W of light, then 20 s of grid checks, then a soft start of 1 kW per second         |
| Anti-islanding       | grid lost: zero output on the next second; 60 s wait after the grid returns           |
| Over-temperature     | trip at 95.0 °C, reset at 75.0 °C                                                     |
| Power limit          | percent of rating, optional ramp time and revert timeout (SunSpec model 123)          |

Registers 100 to 115 are the test bench: time of day, advance, clouds, ambient temperature, grid, forced heat sink
temperature, reset, and diagnostic counters. Because they are ordinary Modbus registers, the same test steers the
simulator in the same process, behind a virtual port, or at the end of a cable.

## One suite, four links

| `LINK`                 | What is between the test and the device       | Where                |
| ---------------------- | --------------------------------------------- | -------------------- |
| `memory` (default)     | a socket pair in one process, RTU framing     | everywhere, fastest  |
| `socat`                | two pseudo-terminals joined by socat          | CI, Linux, macOS     |
| `tcp`                  | Modbus TCP on 127.0.0.1                       | everywhere           |
| `serial://PORT?baud=`  | a real RS-485 line, two USB adapters          | the bench            |

Markers decide what runs where: `once`, `rtu`, `tcp`, `port`, `bench`, `internal`, `pages`.

## Three clients

1. **The project's client** (`client.py`): builds frames by hand, can send damaged ones, checks every answer.
2. **pymodbus**: a third-party Modbus library.
3. **pysunspec2**: the official SunSpec client; its model JSON files are also the oracle for the register map.

## From a test run to the visual page

1. `TapLink` records every byte a test sends or receives; `step("...")` adds plain-language steps.
2. At the end of the run `conftest.py` writes `evidence/run-<link>.json`.
3. `scripts/build_pages.py` merges the three runs, adds the mutation result and the register map, and inlines
   everything into `docs/solar-inverter.html`.
4. The page holds a **JavaScript twin** of the simulator (`site/js/twin.js`). `build_pages.py` records ten
   conversations with the Python simulator (2572 answers); `node site/test/twin.test.mjs` replays them against
   the twin and fails on the first differing byte.
5. `tests/test_pages.py` opens the page in Chromium: every view loads, every planted bug turns its own check red,
   a healthy day turns none red.

Russian texts for tests, steps and mutants are in `site/i18n/ru.json`; `build_pages.py --check` fails if one is
missing.

## Mutation check

`scripts/mutants.py` applies one small change at a time to a copy of the source, runs the whole suite and records
which tests failed. A control run without a change must pass. Result: 38 of 38 caught. Eight of the mutants can be
switched on in the live view of the page.

## How to read the results

- **Allure**: suites by link, each test titled with its sentence, steps and attachments.
- **Visual page → Last test run**: the same sentences with the recorded frames, each frame explained.
- **Visual page → Bug hunt**: each planted bug, the changed lines, the tests that caught it.

## Limits

- The simulator is not a certified inverter model. Limits such as 60 s and 95 °C are its own datasheet, chosen to
  resemble real products; they are not taken from a grid code.
- Reactive power, power factor control and three-phase models are not implemented.
- Timing on virtual links says nothing about a real line; that is what the bench run is for.

## Glossary

| Term           | Meaning                                                                                   |
| -------------- | ----------------------------------------------------------------------------------------- |
| Anti-islanding | The inverter must stop feeding in when the grid is down, so a line under repair is dead    |
| Clipping       | The array could give more than the inverter's rating; the output stays flat at the rating  |
| CRC-16         | The checksum at the end of an RTU frame                                                    |
| MBAP           | The 7-byte header of Modbus TCP                                                            |
| MPPT           | Maximum power point tracking: the inverter takes all the power the array can give          |
| PDU            | The function code and its data, the same on RTU and TCP                                    |
| RS-485         | The two-wire serial line most inverters use for Modbus RTU                                 |
| Scale factor   | A register holding the power of ten that turns a raw integer into real units               |
| SunSpec        | The standard register map for solar and storage devices                                    |
| Unit id        | The Modbus address of a device, 1 to 247                                                   |

## Sources

- MODBUS Application Protocol Specification V1.1b3, modbus.org
- MODBUS over Serial Line Specification and Implementation Guide V1.02, modbus.org
- MODBUS Messaging on TCP/IP Implementation Guide V1.0b, modbus.org
- SunSpec Device Information Model Specification and the model definitions, sunspec.org and github.com/sunspec/models
