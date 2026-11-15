"""Run the simulated inverter or watch one from the command line.

    python -m inverter_lab serve --tcp 5020
    python -m inverter_lab serve --serial /dev/ttyUSB0 --baud 9600 --time-scale 600 --start 04:00
    python -m inverter_lab watch tcp://127.0.0.1:5020
    python -m inverter_lab watch "serial:///dev/ttyUSB1?baud=9600"

``serve`` with ``--time-scale 600`` lets ten simulated minutes pass every real second, so a whole day
takes about two and a half minutes. Without it the clock moves only when a test tells it to.
"""

from __future__ import annotations

import argparse
import sys
import time

from inverter_lab import __version__
from inverter_lab.client import Master, NoResponse, RtuMaster, TcpMaster
from inverter_lab.device import SIM_BASE, SIM_CLOCK_MIN, InverterDevice
from inverter_lab.links import open_serial, open_tcp, parse_target
from inverter_lab.reader import SunSpecReader
from inverter_lab.server import RealTimeClock, RtuServer, TcpServer
from inverter_lab.sunspec import EVENT_NAMES, STATE_NAMES


def serve(args: argparse.Namespace) -> int:
    device = InverterDevice(args.unit)
    hours, _, mins = args.start.partition(":")
    device.inverter.clock = int(hours) * 3600 + int(mins or 0) * 60
    device.time_scale = args.time_scale
    clock = RealTimeClock(device).start()
    servers: list[RtuServer | TcpServer] = []
    if args.tcp is not None:
        tcp = TcpServer(device, host=args.host, port=args.tcp).start()
        servers.append(tcp)
        print(f"Modbus TCP on {tcp.host}:{tcp.port}, unit {args.unit}")
    if args.serial is not None:
        servers.append(RtuServer(open_serial(f"{args.serial}?baud={args.baud}&parity={args.parity}"), device).start())
        print(f"Modbus RTU on {args.serial}, {args.baud} 8{args.parity}1, unit {args.unit}")
    if not servers:
        print("nothing to serve: give --tcp PORT, --serial PORT or both", file=sys.stderr)
        return 2
    print(f"inverter_lab {__version__}: SIM-5000-1P, clock {args.start}, time scale {args.time_scale}. Ctrl+C stops.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        clock.stop()
        for server in servers:
            server.stop()
    return 0


def connect(target: str, unit: int) -> Master:
    kind, rest = parse_target(target)
    if kind == "tcp":
        host, _, port = rest.partition(":")
        return TcpMaster(open_tcp(host, int(port or 502)), unit, timeout=2.0, retries=1)
    return RtuMaster(open_serial(rest), unit, timeout=2.0, retries=1)


def status_line(master: Master, reader: SunSpecReader) -> str:
    mins, secs = master.read_holding(SIM_BASE + SIM_CLOCK_MIN, 2)
    now = reader.measurements(101)
    controls = reader.model(123)
    watts = float(now["W"])  # type: ignore[arg-type]
    bar = "#" * round(watts / 250)
    events = [name for bit, name in EVENT_NAMES.items() if int(now["Evt1"]) & bit]  # type: ignore[arg-type]
    limit = f"limit {controls['WMaxLimPct']} %" if controls["WMaxLim_Ena"] == 1 else "no limit"
    return (
        f"{mins // 60:02d}:{mins % 60:02d}:{secs:02d}  {STATE_NAMES.get(int(now['St']), '?'):<9}"  # type: ignore[arg-type]
        f"  {watts:6.0f} W  [{bar:<20}]  {now['PhVphA']:5.1f} V  {now['A']:5.2f} A"
        f"  {now['TmpSnk']:5.1f} C  {float(now['WH']) / 1000:9.3f} kWh  {limit}"  # type: ignore[arg-type]
        f"{'  ' + ' '.join(events) if events else ''}"
    )


def watch(args: argparse.Namespace) -> int:
    master = connect(args.target, args.unit)
    reader = SunSpecReader(master)
    common = reader.model(1)
    print(f"{common['Mn']} {common['Md']}, serial {common['SN']}, version {common['Vr']}")
    try:
        while True:
            try:
                print(status_line(master, reader), flush=True)
            except NoResponse:
                print("no answer", flush=True)
            if args.once:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m inverter_lab", description=__doc__.split("\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)

    s = commands.add_parser("serve", help="run the simulated inverter")
    s.add_argument("--tcp", type=int, metavar="PORT", help="serve Modbus TCP on this port")
    s.add_argument("--host", default="127.0.0.1", help="address for Modbus TCP (default 127.0.0.1)")
    s.add_argument("--serial", metavar="PORT", help="serve Modbus RTU on this serial port")
    s.add_argument("--baud", type=int, default=9600)
    s.add_argument("--parity", default="N", choices=["N", "E", "O"])
    s.add_argument("--unit", type=int, default=1, help="Modbus address of the inverter (default 1)")
    s.add_argument("--time-scale", type=int, default=0, help="simulated seconds per real second (default 0)")
    s.add_argument("--start", default="12:00", metavar="HH:MM", help="time of day at start (default 12:00)")
    s.set_defaults(run=serve)

    w = commands.add_parser("watch", help="poll an inverter and print one line per reading")
    w.add_argument("target", help="tcp://HOST:PORT or serial://PORT?baud=9600")
    w.add_argument("--unit", type=int, default=1)
    w.add_argument("--interval", type=float, default=1.0, help="seconds between readings (default 1)")
    w.add_argument("--once", action="store_true", help="print one reading and exit")
    w.set_defaults(run=watch)

    args = parser.parse_args(argv)
    result: int = args.run(args)
    return result


if __name__ == "__main__":
    sys.exit(main())
