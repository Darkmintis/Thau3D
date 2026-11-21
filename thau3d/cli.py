"""Command line interface.

The CLI is the product surface an agent talks to:

    thau3d validate house.thau.json     # is this a real building?
    thau3d build    house.thau.json     # GLB + manifest
    thau3d report   house.thau.json     # room schedule, areas, assumptions
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .build import Builder
from .spec import FT, SpecInvalid, SpecError, load_spec, validate
from .verify import verify


def _fmt(value: float, units: str, area: bool = False) -> str:
    factor = 1.0 / FT if units == "ft" else 1.0
    number = value * factor
    if area:
        return f"{number:.0f} sq ft" if units == "ft" else f"{number:.1f} m²"
    return f"{number:.2f} ft" if units == "ft" else f"{number:.2f} m"


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        building = load_spec(args.spec)
    except SpecInvalid as error:
        if args.json:
            print(json.dumps({"ok": False, "problems": [str(i) for i in error.errors]}))
        else:
            print(f"{args.spec}: {len(error.errors)} problem(s)\n")
            for issue in error.issues:
                print(f"  {issue}")
        return 1
    except SpecError as error:
        if args.json:
            print(json.dumps({"ok": False, "problems": [str(error)]}))
        else:
            print(f"error: {error}")
        return 1

    issues = validate(building)
    warnings = [issue for issue in issues if issue.level == "warning"]
    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "name": building.name,
                    "storeys": len(building.storeys),
                    "spaces": sum(len(storey.spaces) for storey in building.storeys),
                    "warnings": [issue.message for issue in warnings],
                }
            )
        )
        return 0

    print(f"✓ {building.name} is a valid building")
    print(
        f"  {len(building.storeys)} storeys · "
        f"{sum(len(storey.spaces) for storey in building.storeys)} spaces · "
        f"{_fmt(building.width, building.units)} × {_fmt(building.depth, building.units)}"
    )
    for issue in warnings:
        print(f"  ⚠ {issue.path}: {issue.message}")
    return 0


def cmd_build(args: argparse.Namespace) -> int:
    try:
        building = load_spec(args.spec)
    except SpecInvalid as error:
        print(f"{args.spec}: {len(error.errors)} problem(s)\n", file=sys.stderr)
        for issue in error.issues:
            print(f"  {issue}", file=sys.stderr)
        return 1
    except SpecError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    stem = args.stem or Path(args.spec).stem
    if stem.endswith(".thau"):
        stem = stem[: -len(".thau")]
    try:
        report = Builder(building).export(args.out, stem)
    except Exception as error:  # surfaced to the agent, not swallowed
        print(f"error while building: {type(error).__name__}: {error}", file=sys.stderr)
        raise

    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "glb": str(report.glb),
                    "manifest": str(report.manifest),
                    "nodes": report.nodes,
                    "triangles": report.triangles,
                    "bytes": report.bytes,
                    "spaces": len(report.spaces),
                    "warnings": report.warnings,
                }
            )
        )
        return 0

    print(report.summary())
    print(f"  → {report.glb}")
    print(f"  → {report.manifest}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        building = load_spec(args.spec)
    except SpecInvalid as error:
        print(f"{args.spec}: {len(error.errors)} problem(s); fix validation before verifying\n", file=sys.stderr)
        for issue in error.issues:
            print(f"  {issue}", file=sys.stderr)
        return 1
    except SpecError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    checks = verify(building)
    failures = [check for check in checks if check.level == "fail"]

    if args.json:
        print(
            json.dumps(
                {
                    "ok": not failures,
                    "checks": [{"level": c.level, "name": c.name, "detail": c.detail} for c in checks],
                }
            )
        )
        return 0 if not failures else 1

    marks = {"pass": "  ok  ", "warn": " warn ", "fail": " FAIL "}
    print(f"{building.name}")
    print(f"{'':8}{'check':<22} detail")
    for check in checks:
        print(f"[{marks[check.level]}] {check.name:<22} {check.detail}")
    passed = sum(1 for check in checks if check.level == "pass")
    warned = sum(1 for check in checks if check.level == "warn")
    print(f"\n{passed} passed · {warned} warnings · {len(failures)} failures")
    return 0 if not failures else 1

def cmd_report(args: argparse.Namespace) -> int:
    try:
        building = load_spec(args.spec)
    except (SpecError, SpecInvalid) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    units = building.units
    rows = []
    for storey in building.storeys:
        net = sum(space.area for space in storey.spaces)
        rows.append(
            {
                "storey": storey.id,
                "level": storey.index,
                "base": storey.base,
                "height": storey.height,
                "clear": storey.clear,
                "spaces": [
                    {
                        "id": space.id,
                        "type": space.type,
                        "width": space.width,
                        "depth": space.depth,
                        "area": space.area,
                    }
                    for space in storey.spaces
                ],
                "net_area": net,
            }
        )

    if args.json:
        print(json.dumps({"name": building.name, "units": units, "storeys": rows}, indent=2))
        return 0

    print(f"{building.name}")
    print(f"footprint {_fmt(building.width, units)} × {_fmt(building.depth, units)}")
    for row in rows:
        print(
            f"\n  {row['storey']}  level {row['level']}  "
            f"floor {_fmt(row['height'], units)}  clear {_fmt(row['clear'], units)}"
        )
        for space in row["spaces"]:
            print(
                f"    {space['id']:<14} {space['type']:<9} "
                f"{_fmt(space['width'], units):>9} × {_fmt(space['depth'], units):>9}   "
                f"{_fmt(space['area'], units, area=True):>10}"
            )
        print(f"    {'net':<14} {'':<9} {'':>9}   {'':>9}   {_fmt(row['net_area'], units, area=True):>10}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="thau3d",
        description="Describe a place. Get a building you can walk through.",
    )
    parser.add_argument("--version", action="version", version="thau3d 0.1.0")
    sub = parser.add_subparsers(dest="command", required=True)

    validate_parser = sub.add_parser("validate", help="check a spec without building it")
    validate_parser.add_argument("spec")
    validate_parser.add_argument("--json", action="store_true")
    validate_parser.set_defaults(func=cmd_validate)

    build_parser_cmd = sub.add_parser("build", help="build a GLB and manifest from a spec")
    build_parser_cmd.add_argument("spec")
    build_parser_cmd.add_argument("-o", "--out", default="build")
    build_parser_cmd.add_argument("--stem", default=None)
    build_parser_cmd.add_argument("--json", action="store_true")
    build_parser_cmd.set_defaults(func=cmd_build)

    verify_parser = sub.add_parser("verify", help="check dimensions: heights, doors, room sizes, stairs, daylight")
    verify_parser.add_argument("spec")
    verify_parser.add_argument("--json", action="store_true")
    verify_parser.set_defaults(func=cmd_verify)

    report_parser = sub.add_parser("report", help="print the room schedule")
    report_parser.add_argument("spec")
    report_parser.add_argument("--json", action="store_true")
    report_parser.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    _use_utf8_console()
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


def _use_utf8_console() -> None:
    """Windows terminals default to a legacy code page; make our output portable."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):
            pass


if __name__ == "__main__":
    raise SystemExit(main())
