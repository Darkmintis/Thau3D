"""Spec loading, normalisation and validation.

A Thau3D spec is deliberately *room-first*: you describe the spaces a storey is
made of, and the builder derives walls, doors, windows and slabs from how those
spaces touch each other. That keeps the file short enough for a person to read
and for a language model to write correctly.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

FT = 0.3048
SUPPORTED_VERSION = "0.1"

SPACE_TYPES = {
    "living", "bedroom", "kitchen", "dining", "bath", "wc", "hall", "stair",
    "entry", "study", "utility", "terrace", "balcony", "garage", "office",
    "store", "lounge",
}

HABITABLE = {"living", "bedroom", "kitchen", "dining", "study", "office", "lounge"}


class SpecError(Exception):
    """Raised when a spec cannot be turned into a building at all."""


@dataclass
class Issue:
    level: str  # "error" | "warning"
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper():7} {self.path or '<spec>'}: {self.message}"


@dataclass
class Space:
    id: str
    type: str
    name: str
    storey: str
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return self.x1 - self.x0

    @property
    def depth(self) -> float:
        return self.y1 - self.y0

    @property
    def area(self) -> float:
        return self.width * self.depth

    @property
    def center(self) -> tuple[float, float]:
        return ((self.x0 + self.x1) / 2.0, (self.y0 + self.y1) / 2.0)


@dataclass
class Storey:
    id: str
    index: int
    base: float
    height: float
    clear: float
    spaces: list[Space] = field(default_factory=list)

    @property
    def top(self) -> float:
        return self.base + self.height


@dataclass
class Stair:
    id: str
    storey: str
    x0: float
    y0: float
    x1: float
    y1: float
    form: str = "u"
    width: float = 1.2

    @property
    def rect(self) -> tuple[float, float, float, float]:
        return (self.x0, self.y0, self.x1, self.y1)


@dataclass
class WindowSpec:
    space: str
    side: str
    width: float
    sill: float
    head: float
    offset: float = 0.0
    storey: str | None = None


@dataclass
class DoorSpec:
    between: tuple[str, str]
    width: float
    offset: float = 0.0
    height: float = 2.1


@dataclass
class Balcony:
    """A slab projecting past an elevation, with a glazed balustrade."""

    id: str
    storey: str
    side: str
    span: tuple[float, float]
    depth: float
    railing: float = 1.05
    door: float = 1.9


SIDES = ("front", "back", "left", "right")


def stair_flight(stair: "Stair", storey: "Storey") -> dict:
    """The single definition of a stair's geometry, shared by builder and verify.

    Keeping this in one place is why the builder and the checks cannot disagree
    about riser height or tread depth.
    """
    depth = stair.y1 - stair.y0
    if stair.form == "straight":
        width = min(stair.width, (stair.x1 - stair.x0) - 0.1)
        count = max(6, int(math.ceil(storey.height / 0.19)))
        landing = 0.0
        tread = depth / count
        riser = storey.height / count
    else:
        width = max(0.85, min(stair.width, (stair.x1 - stair.x0) / 2.0 - 0.05))
        count = max(6, int(math.ceil((storey.height / 2.0) / 0.19)))
        landing = min(max(1.0, width), depth * 0.4)
        tread = (depth - landing) / count
        riser = storey.height / (2.0 * count)
    return {
        "count": count,
        "riser": riser,
        "tread": tread,
        "width": width,
        "landing": landing,
        "depth": depth,
    }

def balcony_rect(balcony: Balcony, building: "Building") -> tuple[float, float, float, float]:
    """Plan rectangle (x0, y0, x1, y1) the balcony occupies."""
    a0, a1 = balcony.span
    depth = balcony.depth
    if balcony.side == "front":
        return (a0, -depth, a1, 0.0)
    if balcony.side == "back":
        return (a0, building.depth, a1, building.depth + depth)
    if balcony.side == "left":
        return (-depth, a0, 0.0, a1)
    return (building.width, a0, building.width + depth, a1)


@dataclass
class Building:
    name: str
    units: str
    width: float
    depth: float
    storeys: list[Storey]
    stairs: list[Stair]
    windows: list[WindowSpec]
    doors: list[DoorSpec]
    balconies: list[Balcony]
    entrance: dict
    roof: dict
    site: dict
    palette_overrides: dict[str, str]
    defaults: dict
    source: Path | None = None

    @property
    def top(self) -> float:
        return self.storeys[-1].top if self.storeys else 0.0

    def storey(self, storey_id: str) -> Storey | None:
        for item in self.storeys:
            if item.id == storey_id:
                return item
        return None

    def space(self, space_id: str, storey_id: str | None = None) -> Space | None:
        if storey_id:
            storey = self.storey(storey_id)
            if storey is None:
                return None
            for space in storey.spaces:
                if space.id == space_id:
                    return space
            return None
        for storey in self.storeys:
            for space in storey.spaces:
                if space.id == space_id:
                    return space
        return None


# ------------------------------------------------------------------ defaults
DEFAULT_DEFAULTS = {
    "storeyHeight": 10.0,
    "clearHeight": 9.25,
    "slab": 0.6,
    "exteriorWall": 0.75,
    "interiorWall": 0.375,
    "doorWidth": 2.75,
    "doorHeight": 7.0,
    "windowSill": 3.0,
    "windowHead": 7.2,
}


def load_spec(path: str | Path) -> Building:
    path = Path(path)
    if not path.exists():
        raise SpecError(f"spec not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SpecError(
            f"{path.name} is not valid JSON at line {error.lineno}, column {error.colno}: {error.msg}"
        ) from error
    building = _parse(raw, path)
    issues = validate(building)
    errors = [issue for issue in issues if issue.level == "error"]
    if errors:
        raise SpecInvalid(errors, issues)
    return building


class SpecInvalid(SpecError):
    def __init__(self, errors: list[Issue], issues: list[Issue]) -> None:
        self.errors = errors
        self.issues = issues
        lines = "\n".join(f"  - {issue.message}" for issue in errors)
        super().__init__(f"spec has {len(errors)} problem(s):\n{lines}")


# -------------------------------------------------------------------- parsing
def _parse(raw: dict, path: Path | None) -> Building:
    if not isinstance(raw, dict):
        raise SpecError("spec root must be a JSON object")

    version = str(raw.get("version", SUPPORTED_VERSION))
    if version.split(".")[0] != SUPPORTED_VERSION.split(".")[0]:
        raise SpecError(f"unsupported spec version {version}; this build understands {SUPPORTED_VERSION}")

    units = str(raw.get("units", "ft")).lower()
    if units not in ("ft", "m"):
        raise SpecError(f'units must be "ft" or "m", got {units!r}')
    scale = FT if units == "ft" else 1.0

    defaults_raw = dict(DEFAULT_DEFAULTS)
    defaults_raw.update(raw.get("defaults", {}) or {})
    defaults = {key: float(value) for key, value in defaults_raw.items()}
    defaults_m = {key: value * scale for key, value in defaults.items()}

    footprint = raw.get("footprint") or {}
    width = _number(footprint.get("width"), "footprint.width") * scale
    depth = _number(footprint.get("depth"), "footprint.depth") * scale
    if width <= 0 or depth <= 0:
        raise SpecError("footprint.width and footprint.depth must be positive")

    storeys_raw = raw.get("storeys")
    if not isinstance(storeys_raw, list) or not storeys_raw:
        raise SpecError('"storeys" must be a non-empty array')

    storeys: list[Storey] = []
    base = 0.0
    for index, storey_raw in enumerate(storeys_raw):
        if not isinstance(storey_raw, dict):
            raise SpecError(f"storeys[{index}] must be an object")
        storey_id = str(storey_raw.get("id") or f"level{index}")
        height = float(storey_raw.get("height", defaults["storeyHeight"])) * scale
        clear = float(storey_raw.get("clear", defaults["clearHeight"])) * scale
        if height <= 0:
            raise SpecError(f"storeys[{index}].height must be positive")
        if clear > height:
            raise SpecError(
                f'storey "{storey_id}" has clear height {clear / scale:g} above its floor-to-floor height {height / scale:g}'
            )
        spaces = _parse_spaces(storey_raw.get("spaces"), storey_id, scale)
        storeys.append(Storey(storey_id, index, base, height, clear, spaces))
        base += height

    stairs = []
    for index, stair_raw in enumerate(raw.get("stairs", []) or []):
        stairs.append(
            Stair(
                id=str(stair_raw.get("id") or f"stair{index}"),
                storey=str(stair_raw.get("storey") or storeys[0].id),
                x0=_number(_axis(stair_raw.get("x"), 0), "stairs.x[0]") * scale,
                y0=_number(_axis(stair_raw.get("y"), 0), "stairs.y[0]") * scale,
                x1=_number(_axis(stair_raw.get("x"), 1), "stairs.x[1]") * scale,
                y1=_number(_axis(stair_raw.get("y"), 1), "stairs.y[1]") * scale,
                form=str(stair_raw.get("form") or "u").lower(),
                width=float(stair_raw.get("width", 4.0)) * scale,
            )
        )

    windows = [
        WindowSpec(
            space=str(item.get("space") or ""),
            side=str(item.get("side") or "front").lower(),
            storey=(str(item["storey"]) if item.get("storey") else None),
            width=float(item.get("width", 5.0)) * scale,
            sill=float(item.get("sill", defaults["windowSill"])) * scale,
            head=float(item.get("head", defaults["windowHead"])) * scale,
            offset=float(item.get("offset", 0.0)) * scale,
        )
        for item in raw.get("windows", []) or []
    ]

    doors = []
    for item in raw.get("doors", []) or []:
        pair = item.get("between") or []
        if len(pair) != 2:
            raise SpecError('each door needs "between": ["spaceA", "spaceB"]')
        doors.append(
            DoorSpec(
                between=(str(pair[0]), str(pair[1])),
                width=float(item.get("width", defaults["doorWidth"])) * scale,
                offset=float(item.get("offset", 0.0)) * scale,
                height=float(item.get("height", defaults["doorHeight"])) * scale,
            )
        )

    balconies = []
    for index, item in enumerate(raw.get("balconies", []) or []):
        side = str(item.get("side") or "front").lower()
        if side not in SIDES:
            raise SpecError(f'balconies[{index}].side must be one of {SIDES}, got {side!r}')
        span = item.get("span")
        if not isinstance(span, (list, tuple)) or len(span) != 2:
            raise SpecError(f'balconies[{index}] needs "span": [start, end] measured along the {side} elevation')
        balconies.append(
            Balcony(
                id=str(item.get("id") or f"balcony{index + 1}"),
                storey=str(item.get("storey") or storeys[0].id),
                side=side,
                span=(
                    _number(_axis(span, 0), f"balconies[{index}].span[0]") * scale,
                    _number(_axis(span, 1), f"balconies[{index}].span[1]") * scale,
                ),
                depth=float(item.get("depth", 4.5)) * scale,
                railing=float(item.get("railing", 3.4)) * scale,
                door=float(item.get("door", 6.0)) * scale,
            )
        )
    site_raw = dict(raw.get("site") or {})

    path_raw = site_raw.get("path") or {}
    path: dict = {}
    if path_raw:
        span = path_raw.get("x") or [width / scale * 0.45, width / scale * 0.55]
        path = {
            "x": [float(span[0]) * scale, float(span[1]) * scale],
            "from": float(path_raw.get("from", -6.0)) * scale,
            "to": float(path_raw.get("to", 0.0)) * scale,
        }

    site = {
        "width": float(site_raw.get("width", width / scale + 14.0)) * scale,
        "depth": float(site_raw.get("depth", depth / scale + 16.0)) * scale,
        "surface": str(site_raw.get("surface") or "ground"),
        "path": path,
        "apron": float(site_raw.get("apron", 3.0)) * scale,
    }

    entrance_raw = dict(raw.get("entrance") or {})
    entrance = {
        "space": str(entrance_raw.get("space") or ""),
        "side": str(entrance_raw.get("side") or "front").lower(),
        "width": float(entrance_raw.get("width", 3.5)) * scale,
        "height": float(entrance_raw.get("height", 7.2)) * scale,
    }

    roof_raw = dict(raw.get("roof") or {})
    roof = {
        "type": str(roof_raw.get("type") or "terrace").lower(),
        "parapet": float(roof_raw.get("parapet", 3.0)) * scale,
        "overhang": float(roof_raw.get("overhang", 0.6)) * scale,
        "pitch": float(roof_raw.get("pitch", 22.0)),
        "ridge": str(roof_raw.get("ridge") or "x").lower(),
    }

    overrides = {str(k): str(v) for k, v in (raw.get("materials") or {}).items()}

    return Building(
        name=str(raw.get("name") or "Untitled"),
        units=units,
        width=width,
        depth=depth,
        storeys=storeys,
        stairs=stairs,
        windows=windows,
        doors=doors,
        balconies=balconies,
        entrance=entrance,
        roof=roof,
        site=site,
        palette_overrides=overrides,
        defaults=defaults_m,
        source=path,
    )


def _parse_spaces(raw_spaces, storey_id: str, scale: float) -> list[Space]:
    if not isinstance(raw_spaces, list) or not raw_spaces:
        raise SpecError(f'storey "{storey_id}" needs a non-empty "spaces" array')
    spaces: list[Space] = []
    for index, item in enumerate(raw_spaces):
        if not isinstance(item, dict):
            raise SpecError(f'storey "{storey_id}" spaces[{index}] must be an object')
        space_id = str(item.get("id") or f"{storey_id}_{index}")
        space_type = str(item.get("type") or "living").lower()
        x0 = _number(_axis(item.get("x"), 0), f"{storey_id}.{space_id}.x[0]") * scale
        x1 = _number(_axis(item.get("x"), 1), f"{storey_id}.{space_id}.x[1]") * scale
        y0 = _number(_axis(item.get("y"), 0), f"{storey_id}.{space_id}.y[0]") * scale
        y1 = _number(_axis(item.get("y"), 1), f"{storey_id}.{space_id}.y[1]") * scale
        if x1 <= x0 or y1 <= y0:
            raise SpecError(f'space "{space_id}" has an inverted rectangle: x={[x0 / scale, x1 / scale]}, y={[y0 / scale, y1 / scale]}')
        spaces.append(
            Space(
                id=space_id,
                type=space_type,
                name=str(item.get("name") or space_id.replace("_", " ").title()),
                storey=storey_id,
                x0=x0,
                y0=y0,
                x1=x1,
                y1=y1,
            )
        )
    return spaces


def _axis(value, index):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    return value[index]


def _number(value, label: str) -> float:
    if value is None:
        raise SpecError(f"missing required number {label}")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise SpecError(f"{label} must be a number, got {value!r}") from error


# ----------------------------------------------------------------- validation
def validate(building: Building) -> list[Issue]:
    """Return every problem found, most useful first."""
    issues: list[Issue] = []
    eps = 1e-6

    for storey in building.storeys:
        # inside the footprint
        for space in storey.spaces:
            if (
                space.x0 < -eps
                or space.y0 < -eps
                or space.x1 > building.width + eps
                or space.y1 > building.depth + eps
            ):
                issues.append(
                    Issue(
                        "error",
                        space.id,
                        f'"{space.id}" runs outside the footprint '
                        f"({_fmt(space.x0, building.units)}..{_fmt(space.x1, building.units)} x, "
                        f"{_fmt(space.y0, building.units)}..{_fmt(space.y1, building.units)} y) "
                        f"— footprint is {_fmt(building.width, building.units)} x {_fmt(building.depth, building.units)}",
                    )
                )
            if space.type not in SPACE_TYPES:
                close = _closest(space.type, SPACE_TYPES)
                hint = f' — did you mean "{close}"?' if close else ""
                issues.append(
                    Issue("warning", space.id, f'unknown space type "{space.type}"{hint}')
                )

        # overlapping rooms
        for i, first in enumerate(storey.spaces):
            for second in storey.spaces[i + 1 :]:
                ox = min(first.x1, second.x1) - max(first.x0, second.x0)
                oy = min(first.y1, second.y1) - max(first.y0, second.y0)
                if ox > eps and oy > eps:
                    issues.append(
                        Issue(
                            "error",
                            f"{first.id}/{second.id}",
                            f'"{first.id}" and "{second.id}" overlap by '
                            f"{_fmt(ox, building.units)} x {_fmt(oy, building.units)}; "
                            "rooms on a storey must tile without overlapping",
                        )
                    )

        # coverage of the footprint
        covered = sum(space.area for space in storey.spaces)
        target = building.width * building.depth
        if covered < target - 1e-3 and storey.index == 0:
            issues.append(
                Issue(
                    "warning",
                    storey.id,
                    f"rooms cover {_fmt(covered, building.units, area=True)} of a "
                    f"{_fmt(target, building.units, area=True)} footprint; the gap becomes unassigned floor",
                )
            )

    # storey connectivity: every storey after the first needs a stair from below
    for storey in building.storeys[1:]:
        below = building.storeys[storey.index - 1]
        has_stair = any(stair.storey == below.id for stair in building.stairs)
        if not has_stair:
            issues.append(
                Issue(
                    "warning",
                    storey.id,
                    f'storey "{storey.id}" has no stair starting on "{below.id}"; it will not be reachable on foot',
                )
            )

    for stair in building.stairs:
        storey = building.storey(stair.storey)
        if storey is None:
            issues.append(Issue("error", stair.id, f'stair refers to unknown storey "{stair.storey}"'))
            continue
        inside = any(
            stair.x0 >= space.x0 - eps
            and stair.x1 <= space.x1 + eps
            and stair.y0 >= space.y0 - eps
            and stair.y1 <= space.y1 + eps
            for space in storey.spaces
        )
        if not inside:
            issues.append(
                Issue(
                    "error",
                    stair.id,
                    f'stair "{stair.id}" is not contained by any space on "{stair.storey}"',
                )
            )
        longest = max(stair.x1 - stair.x0, stair.y1 - stair.y0)
        if longest < stair.width * 1.5:
            issues.append(
                Issue(
                    "warning",
                    stair.id,
                    f'stair "{stair.id}" is only {_fmt(longest, building.units)} long for a '
                    f"{_fmt(stair.width, building.units)} wide flight; it will be steep",
                )
            )

    for window in building.windows:
        space = building.space(window.space, window.storey)
        if space is None:
            issues.append(
                Issue("error", "windows", f'window refers to unknown space "{window.space}"')
            )
            continue
        span = _side_length(space, window.side, building)
        if span is not None and window.width > span + eps:
            issues.append(
                Issue(
                    "warning",
                    window.space,
                    f'window on the {window.side} side is {_fmt(window.width, building.units)} wide '
                    f"but that wall is only {_fmt(span, building.units)}",
                )
            )
        if window.head <= window.sill:
            issues.append(
                Issue("error", window.space, "window head must sit above its sill")
            )

    for balcony in building.balconies:
        storey = building.storey(balcony.storey)
        if storey is None:
            issues.append(Issue("error", balcony.id, f'balcony refers to unknown storey "{balcony.storey}"'))
            continue
        if storey.index == 0:
            issues.append(
                Issue(
                    "warning",
                    balcony.id,
                    "balcony sits on the ground storey; it will read as a terrace, not a projecting balcony",
                )
            )
        span = balcony.span[1] - balcony.span[0]
        side_length = building.width if balcony.side in ("front", "back") else building.depth
        if balcony.span[0] < -eps or balcony.span[1] > side_length + eps:
            issues.append(
                Issue(
                    "error",
                    balcony.id,
                    f'balcony span {_fmt(balcony.span[0], building.units)}..{_fmt(balcony.span[1], building.units)} '
                    f"runs past the {balcony.side} elevation, which is only {_fmt(side_length, building.units)} long",
                )
            )
        if span < balcony.door + 0.4:
            issues.append(
                Issue(
                    "warning",
                    balcony.id,
                    f"balcony is {_fmt(span, building.units)} wide but its door needs {_fmt(balcony.door, building.units)}",
                )
            )
        if balcony.depth <= 0.4:
            issues.append(Issue("error", balcony.id, "balcony depth must be greater than 0.4 m"))
        touching = any(
            space.storey == balcony.storey and _touches_side(space, balcony, building)
            for space in storey.spaces
        )
        if not touching:
            issues.append(
                Issue(
                    "warning",
                    balcony.id,
                    f'no space on "{balcony.storey}" touches this part of the {balcony.side} elevation, '
                    "so the balcony door will open from a wall with no room behind it",
                )
            )

    if building.entrance["width"] <= 0:
        issues.append(Issue("error", "entrance", "entrance width must be positive"))

    return issues


def _touches_side(space: Space, balcony: Balcony, building: Building) -> bool:
    eps = 0.02
    if balcony.side in ("front", "back"):
        on_side = space.y0 <= eps if balcony.side == "front" else space.y1 >= building.depth - eps
        return on_side and space.x0 < balcony.span[1] and space.x1 > balcony.span[0]
    on_side = space.x0 <= eps if balcony.side == "left" else space.x1 >= building.width - eps
    return on_side and space.y0 < balcony.span[1] and space.y1 > balcony.span[0]


def _side_length(space: Space, side: str, building: Building) -> float | None:
    if side in ("front", "back"):
        return space.width
    if side in ("left", "right"):
        return space.depth
    return None


def _closest(value: str, options: set[str]) -> str | None:
    import difflib

    match = difflib.get_close_matches(value, list(options), n=1, cutoff=0.6)
    return match[0] if match else None


def _fmt(value: float, units: str, area: bool = False) -> str:
    factor = 1.0 / FT if units == "ft" else 1.0
    suffix = " sq ft" if area and units == "ft" else " m²" if area else ""
    return f"{value * factor:.1f}{suffix}"
