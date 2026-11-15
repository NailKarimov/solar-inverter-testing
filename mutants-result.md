# Mutation check

**38/38 planted bugs caught.** Control run without a planted bug: passed.

| Id | File | Planted bug | Link | Result | Tests that failed |
| --- | --- | --- | --- | --- | --- |
| M01 | `src/inverter_lab/crc.py` | The checksum is calculated from the wrong starting value | memory | caught | 8 |
| M02 | `src/inverter_lab/crc.py` | The two checksum bytes are sent in the wrong order | memory | caught | 231 |
| M03 | `src/inverter_lab/server.py` | The inverter stops checking the checksum and obeys damaged requests | memory | caught | 10 |
| M04 | `src/inverter_lab/server.py` | The inverter answers requests addressed to other devices | memory | caught | 6 |
| M05 | `src/inverter_lab/server.py` | Commands sent to all devices at once are ignored | memory | caught | 1 |
| M06 | `src/inverter_lab/server.py` | Half a request is not forgotten and spoils the next one | memory | caught | 21 |
| M07 | `src/inverter_lab/pdu.py` | A read of 126 registers, one more than the protocol allows, is accepted | memory | caught | 1 |
| M08 | `src/inverter_lab/sunspec.py` | A read may run one register past the end of the map | memory | caught | 3 |
| M09 | `src/inverter_lab/device.py` | A request for a missing register is refused with the wrong reason code | memory | caught | 36 |
| M10 | `src/inverter_lab/server.py` | Network answers lose the number that ties them to their request | tcp | caught | 185 |
| M11 | `src/inverter_lab/server.py` | The network port accepts traffic that is not Modbus | tcp | caught | 1 |
| M12 | `src/inverter_lab/sunspec.py` | The map starts with "Suns" instead of "SunS" | memory | caught | 14 |
| M13 | `src/inverter_lab/sunspec.py` | Every model announces a length one register too long | memory | caught | 123 |
| M14 | `src/inverter_lab/inverter.py` | The current is reported ten times too high (wrong scale factor) | memory | caught | 1 |
| M15 | `src/inverter_lab/sunspec.py` | Temperatures below zero are read as huge positive numbers | memory | caught | 86 |
| M16 | `src/inverter_lab/sunspec.py` | Values the inverter does not have read as zero instead of "not implemented" | memory | caught | 9 |
| M17 | `src/inverter_lab/device.py` | Read-only registers no longer refuse writes cleanly | memory | caught | 10 |
| M18 | `src/inverter_lab/device.py` | A refused command is carried out anyway before it is refused | memory | caught | 10 |
| M19 | `src/inverter_lab/device.py` | A reset is carried out without its key | memory | caught | 2 |
| M20 | `src/inverter_lab/inverter.py` | At full sun the inverter reports a power limit that nobody set | memory | caught | 16 |
| M21 | `src/inverter_lab/inverter.py` | The inverter keeps feeding in when the grid is down | memory | caught | 8 |
| M22 | `src/inverter_lab/inverter.py` | After an outage the inverter reconnects after 6 seconds instead of 60 | memory | caught | 2 |
| M23 | `src/inverter_lab/inverter.py` | The inverter ignores the power limit | memory | caught | 18 |
| M24 | `src/inverter_lab/inverter.py` | A limit that nobody renews stays in force for ever | memory | caught | 2 |
| M25 | `src/inverter_lab/inverter.py` | Renewing a limit does not restart its timer | memory | caught | 1 |
| M26 | `src/inverter_lab/inverter.py` | The over-temperature trip is off by a hair: 95.0 degrees does not trip | memory | caught | 1 |
| M27 | `src/inverter_lab/inverter.py` | After overheating the inverter restarts while it is still hot | memory | caught | 1 |
| M28 | `src/inverter_lab/inverter.py` | The energy counter counts the power before losses: 3 % too much | memory | caught | 2 |
| M29 | `src/inverter_lab/inverter.py` | Conversion losses are understated by one percent | memory | caught | 11 |
| M30 | `src/inverter_lab/inverter.py` | No soft start: the power jumps to full in one step | memory | caught | 6 |
| M31 | `src/inverter_lab/inverter.py` | The inverter skips the grid checks before it starts | memory | caught | 3 |
| M32 | `src/inverter_lab/inverter.py` | The inverter ignores the disconnect command | memory | caught | 2 |
| M33 | `src/inverter_lab/inverter.py` | The inverter gives up too early in weak evening light | memory | caught | 2 |
| M34 | `src/inverter_lab/inverter.py` | The clock runs past midnight and the next morning never comes | memory | caught | 3 |
| M35 | `src/inverter_lab/inverter.py` | Clouds dim the light less than the datasheet says | memory | caught | 4 |
| M36 | `src/inverter_lab/rtu.py` | The client stops checking the checksum of answers | memory | caught | 5 |
| M37 | `src/inverter_lab/client.py` | The client repeats a request the device has already refused | memory | caught | 1 |
| M38 | `src/inverter_lab/client.py` | The client accepts an answer from another device | memory | caught | 1 |
