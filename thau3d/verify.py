"""Dimensional verification.

`validate` answers "is this a coherent building at all?". `verify` answers the
next question: "is it a *usable* one?" — ceiling heights, door widths, room
minimums, stair geometry, daylight. It is the check a client would make by hand
with a scale rule, run before anyone renders a picture.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .spec import Building, Storey, balcony_rect, stair_flight

# thresholds, metres unless noted
MIN_CLEAR_HEIGHT = 2.30
COMFORT_CLEAR_HEIGHT = 2.55
# 32 in clear (0.81 m) is the ADA figure; 0.85 m is a comfortable standard leaf
MIN_DOOR = 0.80
COMFORT_DOOR = 0.85
MIN_CORRIDOR = 0.90
MAX_RISER = 0.19
COMFORT_RISER = 0.18
MIN_TREAD = 0.24
MIN_STAIR_WIDTH = 0.90
MIN_BALCONY_RAIL = 1.00

ROOM_MINIMUMS = {
    "bedroom": 7.0,
    "living": 12.0,
    "lounge": 12.0,
    "kitchen": 5.0,
    "dining": 8.0,
    "bath": 2.4,
    "wc": 1.6,
    "study": 5.0,
    "office": 5.0,
}

DAYLIGHT_RATIO = 0.10  # glazed area vs floor area, a rule of thumb


@dataclass
class Check:
    level: str  # "pass" | "warn" | "fail"
    name: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.level != "fail"


def _m(value: float) -> str:
    return f"{value:.2f} m"


def verify(building: Building) -> list[Check]:
    checks: list[Check] = []

    # ---------------------------------------------------------- clear height
    heights = {storey.id: storey.clear for storey in building.storeys}
    lowest = min(heights.values())
    if lowest < MIN_CLEAR_HEIGHT:
        worst = min(heights, key=heights.get)
        checks.append(
            Check("fail", "ceiling height", f'storey "{worst}" is {_m(lowest)}, minimum is {_m(MIN_CLEAR_HEIGHT)}')
        )
    elif lowest < COMFORT_CLEAR_HEIGHT:
        checks.append(Check("warn", "ceiling height", f"{_m(lowest)} is fine but tight; {_m(COMFORT_CLEAR_HEIGHT)} feels generous"))
    else:
        checks.append(Check("pass", "ceiling height", _m(lowest)))

    # ---------------------------------------------------------------- doors
    door_widths = [door.width for door in building.doors] or [building.defaults["doorWidth"]]
    narrowest = min(door_widths)
    if narrowest < MIN_DOOR:
        checks.append(Check("fail", "door width", f"narrowest door is {_m(narrowest)}, minimum is {_m(MIN_DOOR)}"))
    elif narrowest < COMFORT_DOOR:
        checks.append(Check("warn", "door width", f"{_m(narrowest)} passes furniture but not a wheelchair comfortably"))
    else:
        checks.append(Check("pass", "door width", _m(narrowest)))

    entrance_width = building.entrance["width"]
    if entrance_width < MIN_DOOR * 1.1:
        checks.append(Check("warn", "entrance width", f"{_m(entrance_width)} is narrow for a front door"))
    else:
        checks.append(Check("pass", "entrance width", _m(entrance_width)))

    # ----------------------------------------------------------- room areas
    small: list[str] = []
    tight: list[str] = []
    for storey in building.storeys:
        for space in storey.spaces:
            minimum = ROOM_MINIMUMS.get(space.type)
            if minimum is None:
                continue
            if space.area < minimum:
                small.append(f'{space.id} {space.area:.1f} m² < {minimum:.1f} m²')
            elif space.area < minimum * 1.15:
                tight.append(space.id)
    if small:
        checks.append(Check("fail", "room sizes", "; ".join(small)))
    elif tight:
        checks.append(Check("warn", "room sizes", f"tight but usable: {', '.join(tight)}"))
    else:
        checked = sum(1 for storey in building.storeys for space in storey.spaces if space.type in ROOM_MINIMUMS)
        checks.append(Check("pass", "room sizes", f"{checked} rooms at or above their minimums"))

    # ------------------------------------------------------------ corridors
    narrow_halls = [
        space.id
        for storey in building.storeys
        for space in storey.spaces
        if space.type == "hall" and min(space.width, space.depth) < MIN_CORRIDOR
    ]
    if narrow_halls:
        checks.append(Check("warn", "circulation", f"narrow halls: {', '.join(narrow_halls)}"))
    else:
        halls = [space for storey in building.storeys for space in storey.spaces if space.type == "hall"]
        checks.append(
            Check("pass", "circulation", f"{len(halls)} hallway(s) wider than {_m(MIN_CORRIDOR)}" if halls else "no corridors; rooms connect directly")
        )

    # --------------------------------------------------------------- stairs
    if not building.stairs:
        checks.append(Check("pass", "stairs", "single storey, no stair needed"))
    else:
        for stair in building.stairs:
            storey: Storey | None = building.storey(stair.storey)
            if storey is None:
                continue
            flight = stair_flight(stair, storey)
            count = flight["count"]
            tread = flight["tread"]
            riser = flight["riser"]
            width = flight["width"]

            if riser > MAX_RISER:
                checks.append(Check("fail", f"stair {stair.id}", f"riser {_m(riser)} exceeds {_m(MAX_RISER)}"))
            elif riser > COMFORT_RISER:
                checks.append(Check("warn", f"stair {stair.id}", f"riser {_m(riser)} is steep but legal"))
            elif tread < MIN_TREAD:
                checks.append(Check("fail", f"stair {stair.id}", f"tread {_m(tread)} is shorter than {_m(MIN_TREAD)}"))
            elif width < MIN_STAIR_WIDTH:
                checks.append(Check("warn", f"stair {stair.id}", f"flight width {_m(width)} is narrow"))
            else:
                checks.append(
                    Check("pass", f"stair {stair.id}", f"{count} risers at {_m(riser)}, treads {_m(tread)}, width {_m(width)}")
                )

    # -------------------------------------------------------------- daylight
    windows_by_space: dict[str, float] = {}
    for window in building.windows:
        area = window.width * max(0.0, window.head - window.sill)
        windows_by_space[window.space] = windows_by_space.get(window.space, 0.0) + area
    dark = []
    for storey in building.storeys:
        for space in storey.spaces:
            if space.type not in ("living", "bedroom", "kitchen", "dining", "study", "office", "lounge"):
                continue
            glazed = windows_by_space.get(space.id, 0.0)
            if glazed == 0.0:
                continue
            if glazed < space.area * DAYLIGHT_RATIO:
                dark.append(space.id)
    if dark:
        checks.append(Check("warn", "daylight", f"below 10% glazing: {', '.join(dark)}"))
    else:
        checks.append(Check("pass", "daylight", "every glazed room clears 10% of its floor area"))

    # ------------------------------------------------------------- coverage
    footprint = building.width * building.depth
    for storey in building.storeys:
        covered = sum(space.area for space in storey.spaces)
        ratio = covered / footprint if footprint else 1.0
        if ratio < 0.85:
            checks.append(
                Check("warn", f"coverage {storey.id}", f"{ratio * 100:.0f}% of the footprint is assigned to rooms")
            )
    if not any(check.name.startswith("coverage") for check in checks):
        checks.append(Check("pass", "coverage", "every storey fills the footprint"))

    # ------------------------------------------------------------- balconies
    for balcony in building.balconies:
        if balcony.railing < MIN_BALCONY_RAIL:
            checks.append(
                Check("fail", f"balcony {balcony.id}", f"railing {_m(balcony.railing)} is below {_m(MIN_BALCONY_RAIL)}")
            )
        else:
            x0, y0, x1, y1 = balcony_rect(balcony, building)
            checks.append(
                Check("pass", f"balcony {balcony.id}", f"{(x1 - x0) * (y1 - y0):.1f} m² with a {_m(balcony.railing)} railing")
            )

    # --------------------------------------------------- furniture clearance
    from .build import Builder, _rects_overlap

    probe = Builder(building)
    probe.build()
    blocked_rooms: list[str] = []
    worst = 0.0
    for space_id, zones in probe.door_clearance.items():
        for f_rect in probe.furniture_zones.get(space_id, []):
            for zone in zones:
                ox = min(f_rect[2], zone[2]) - max(f_rect[0], zone[0])
                oy = min(f_rect[3], zone[3]) - max(f_rect[1], zone[1])
                area = max(0.0, ox) * max(0.0, oy)
                worst = max(worst, area)
                # A corner grazing the zone edge is not an obstruction; a piece
                # sitting in the doorway is.
                if area > 0.12 and space_id not in blocked_rooms:
                    blocked_rooms.append(space_id)
    if blocked_rooms:
        checks.append(
            Check("fail", "door clearance", f"furniture intrudes into doorway zone in: {', '.join(blocked_rooms)}")
        )
    else:
        checks.append(
            Check(
                "pass",
                "door clearance",
                f"every doorway and swing zone is clear of furniture (worst corner {worst * 100:.0f} cm²)",
            )
        )

    return checks


def summarise(checks: list[Check]) -> dict:
    return {
        "pass": sum(1 for check in checks if check.level == "pass"),
        "warn": sum(1 for check in checks if check.level == "warn"),
        "fail": sum(1 for check in checks if check.level == "fail"),
    }
