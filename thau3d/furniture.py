"""Procedural furniture, keyed by space type.

Everything here is a handful of boxes and cylinders placed against the walls of
a room. That is deliberate: the point of Thau3D is a *readable, walkable* model
produced in milliseconds, not a photo-real asset pack. Materials carry most of
the realism, and swapping in real furniture GLBs later only changes this file.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import MeshData, box, cylinder
from .spec import Space

MM = 1.0


@dataclass
class Piece:
    name: str
    mesh: MeshData
    material: str
    blocks: bool = True


class Furnisher:
    """Small helper so the room recipes below stay readable."""

    def __init__(self, space: Space, base_z: float, clear: float, glazed_sides: set[str] | None = None) -> None:
        self.space = space
        self.base = base_z
        self.clear = clear
        self.pieces: list[Piece] = []
        self.glazed = glazed_sides or set()

    @property
    def tv_at_front(self) -> bool:
        """A television belongs on a solid wall, never under a window."""
        return "front" not in self.glazed

    @property
    def head_at_back(self) -> bool:
        """A headboard belongs on a solid wall, never under a window."""
        return "back" not in self.glazed

    # -- primitives ---------------------------------------------------------
    def block(
        self,
        name: str,
        center: tuple[float, float],
        size: tuple[float, float, float],
        material: str,
        *,
        z: float | None = None,
        blocks: bool = True,
    ) -> None:
        """Axis-aligned box; ``z`` is the bottom height above the floor."""
        width, depth, height = size
        bottom = self.base + (z if z is not None else 0.0)
        self.pieces.append(
            Piece(
                name=name,
                mesh=box((center[0], center[1], bottom + height / 2.0), (width, depth, height)),
                material=material,
                blocks=blocks,
            )
        )

    def round(
        self,
        name: str,
        center: tuple[float, float],
        radius: float,
        height: float,
        material: str,
        *,
        z: float | None = None,
        blocks: bool = True,
    ) -> None:
        bottom = self.base + (z if z is not None else 0.0)
        self.pieces.append(
            Piece(
                name=name,
                mesh=cylinder((center[0], center[1], bottom + height / 2.0), radius, height, 16),
                material=material,
                blocks=blocks,
            )
        )

    # -- room helpers -------------------------------------------------------
    @property
    def width(self) -> float:
        return self.space.width

    @property
    def depth(self) -> float:
        return self.space.depth

    @property
    def cx(self) -> float:
        return (self.space.x0 + self.space.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.space.y0 + self.space.y1) / 2.0

    def rug(self, width: float, depth: float) -> None:
        self.block("rug", (self.cx, self.cy), (width, depth, 0.012), "rug", z=0.0, blocks=False)


# ---------------------------------------------------------------- bedrooms
def _bedroom(f: Furnisher) -> None:
    bed_w = min(1.65, max(1.2, f.width * 0.42))
    bed_d = min(2.05, max(1.85, f.depth * 0.42))
    back = f.head_at_back
    sign = -1.0 if back else 1.0  # +1 means the bed runs toward +y
    head_y = (f.space.y1 - 0.16) if back else (f.space.y0 + 0.16)
    bed_cy = head_y + sign * (bed_d / 2.0 + 0.06)
    bed_cx = f.cx

    f.block("bed_base", (bed_cx, bed_cy), (bed_w, bed_d, 0.32), "oak", z=0.06)
    f.block("bed_mattress", (bed_cx, bed_cy), (bed_w - 0.08, bed_d - 0.08, 0.24), "linen", z=0.38)
    f.block("bed_duvet", (bed_cx, bed_cy + sign * 0.16), (bed_w - 0.02, bed_d - 0.6, 0.1), "bedding", z=0.62)
    f.block("bed_throw", (bed_cx, bed_cy + sign * (bed_d / 2.0 - 0.32)), (bed_w - 0.02, 0.5, 0.08), "throw", z=0.66)
    f.block("bed_headboard", (bed_cx, head_y), (bed_w + 0.2, 0.09, 1.1), "walnut", z=0.0)
    for index, offset in enumerate((-0.28, 0.28)):
        f.block(
            f"bed_pillow_{index}",
            (bed_cx + offset * bed_w, head_y + sign * 0.42),
            (bed_w * 0.42, 0.34, 0.14),
            "linen",
            z=0.62,
        )

    for side, side_sign in (("l", -1.0), ("r", 1.0)):
        nx = bed_cx + side_sign * (bed_w / 2.0 + 0.34)
        if f.space.x0 + 0.3 < nx < f.space.x1 - 0.3:
            f.block(f"nightstand_{side}", (nx, head_y + sign * 0.28), (0.42, 0.38, 0.52), "oak")
            f.round(f"nightstand_lamp_{side}", (nx, head_y + sign * 0.28), 0.09, 0.3, "led", z=0.55, blocks=False)
            f.block(f"nightstand_stem_{side}", (nx, head_y + sign * 0.28), (0.03, 0.03, 0.16), "metal", z=0.52, blocks=False)

    wardrobe_w = min(1.8, f.width * 0.5)
    f.block("wardrobe", (f.space.x0 + wardrobe_w / 2.0 + 0.2, f.cy), (wardrobe_w, 0.6, 2.3), "oak_light")
    f.block(
        "wardrobe_gap",
        (f.space.x0 + wardrobe_w / 2.0 + 0.2, f.cy - 0.31),
        (wardrobe_w - 0.1, 0.02, 2.1),
        "walnut",
        z=0.1,
        blocks=False,
    )

    f.rug(min(2.6, f.width * 0.7), min(1.8, f.depth * 0.35))


def _living(f: Furnisher) -> None:
    # TV goes on a wall without a window; the sofa faces it.
    sign = 1.0 if f.tv_at_front else -1.0
    sofa_wall = f.space.y1 if sign > 0 else f.space.y0
    sofa_y = sofa_wall - sign * 0.62
    sofa_w = min(2.5, max(1.8, f.width * 0.55))

    f.block("sofa_base", (f.cx, sofa_y), (sofa_w, 0.92, 0.42), "fabric_ivory", z=0.0)
    f.block("sofa_back", (f.cx, sofa_y + sign * 0.36), (sofa_w, 0.2, 0.82), "fabric_ivory", z=0.0)
    f.block("sofa_seat", (f.cx, sofa_y - sign * 0.1), (sofa_w - 0.16, 0.72, 0.14), "linen_dark", z=0.42)
    for index, offset in enumerate((-0.22, 0.22)):
        f.block(
            f"sofa_cushion_{index}",
            (f.cx + offset * sofa_w, sofa_y + sign * 0.2),
            (0.4, 0.14, 0.4),
            "fabric_sage" if index else "fabric_clay",
            z=0.56,
        )
    for side, side_sign in (("l", -1.0), ("r", 1.0)):
        f.block(f"sofa_arm_{side}", (f.cx + side_sign * sofa_w / 2.0, sofa_y), (0.14, 0.92, 0.62), "fabric_ivory", z=0.0)

    table_z = 0.38
    table_y = sofa_y - sign * 1.5
    f.block("coffee_table", (f.cx, table_y), (1.2, 0.62, 0.06), "oak_light", z=table_z)
    for index, (dx, dy) in enumerate(((-0.5, -0.24), (0.5, -0.24), (-0.5, 0.24), (0.5, 0.24))):
        f.block(f"coffee_table_leg_{index}", (f.cx + dx, table_y + dy), (0.05, 0.05, table_z), "metal", blocks=False)

    tv_y = (f.space.y0 + 0.35) if sign > 0 else (f.space.y1 - 0.35)
    f.block("media_console", (f.cx, tv_y), (min(1.9, f.width * 0.6), 0.4, 0.46), "walnut")
    tv_panel_y = tv_y - sign * 0.23
    f.block("tv_panel", (f.cx, tv_panel_y), (min(1.45, f.width * 0.5), 0.06, 0.82), "appliance", z=0.9, blocks=False)

    f.rug(min(2.9, f.width * 0.8), min(2.0, f.depth * 0.42))


def _kitchen(f: Furnisher) -> None:
    run_w = f.width - 0.3
    counter_y = f.space.y1 - 0.32
    f.block("base_cabinets", (f.cx, counter_y), (run_w, 0.6, 0.86), "oak_light")
    f.block("worktop", (f.cx, counter_y), (run_w + 0.04, 0.64, 0.05), "quartz", z=0.86)
    f.block("backsplash", (f.cx, f.space.y1 - 0.06), (run_w, 0.05, 0.55), "ceramic", z=0.91, blocks=False)
    f.block("wall_cabinets", (f.cx, f.space.y1 - 0.2), (run_w - 0.2, 0.36, 0.7), "oak_light", z=1.55)

    sink_x = f.space.x0 + run_w * 0.3
    f.block("sink", (sink_x, counter_y), (0.55, 0.42, 0.04), "steel", z=0.87, blocks=False)
    f.block("tap", (sink_x, counter_y + 0.22), (0.04, 0.04, 0.28), "metal", z=0.91, blocks=False)

    hob_x = f.space.x0 + run_w * 0.66
    f.block("hob", (hob_x, counter_y), (0.6, 0.5, 0.02), "appliance", z=0.91, blocks=False)

    fridge_w = 0.72
    f.block("fridge", (f.space.x1 - fridge_w / 2.0 - 0.05, f.space.y1 - 0.38), (fridge_w, 0.68, 1.92), "steel")

    if f.width > 3.2 and f.depth > 3.4:
        island_w = min(2.2, f.width * 0.55)
        island_y = f.space.y0 + 1.5
        f.block("island", (f.cx, island_y), (island_w, 0.85, 0.9), "oak_light")
        f.block("island_top", (f.cx, island_y), (island_w + 0.06, 0.92, 0.05), "quartz", z=0.9)
        for index, offset in enumerate((-island_w / 4.0, island_w / 4.0)):
            f.block(f"stool_{index}", (f.cx + offset, island_y - 0.72), (0.36, 0.36, 0.44), "fabric_clay")
            f.round(f"stool_stem_{index}", (f.cx + offset, island_y - 0.72), 0.03, 0.24, "metal", z=0.0, blocks=False)


# ------------------------------------------------------------------ dining
def _dining(f: Furnisher) -> None:
    table_w = min(1.9, f.width * 0.62)
    table_d = 0.9
    f.block("table_top", (f.cx, f.cy), (table_w, table_d, 0.06), "oak", z=0.7)
    for index, (dx, dy) in enumerate(((-0.75, -0.34), (0.75, -0.34), (-0.75, 0.34), (0.75, 0.34))):
        f.block(f"table_leg_{index}", (f.cx + dx * table_w / 1.9, f.cy + dy), (0.06, 0.06, 0.7), "metal", blocks=False)
    chair_offsets = (
        (-0.5, -0.72, "n"), (0.5, -0.72, "n"),
        (-0.5, 0.72, "s"), (0.5, 0.72, "s"),
    )
    for index, (dx, dy, _side) in enumerate(chair_offsets):
        chair_x = f.cx + dx * table_w
        chair_y = f.cy + dy
        if not (f.space.y0 + 0.3 < chair_y < f.space.y1 - 0.3):
            continue
        f.block(f"chair_{index}", (chair_x, chair_y), (0.42, 0.42, 0.05), "oak_light", z=0.44)
        f.block(f"chair_back_{index}", (chair_x, chair_y + (0.19 if dy > 0 else -0.19)), (0.42, 0.05, 0.45), "oak_light", z=0.44)
        for leg in (-1, 1):
            f.block(f"chair_leg_{index}_{leg}", (chair_x + leg * 0.17, chair_y), (0.04, 0.4, 0.44), "metal", blocks=False)


# -------------------------------------------------------------------- bath
def _bath(f: Furnisher) -> None:
    small = f.width < 1.9 or f.depth < 1.9

    vanity_w = min(0.9, f.width * 0.5)
    f.block("vanity", (f.space.x0 + vanity_w / 2.0 + 0.05, f.space.y1 - 0.3), (vanity_w, 0.48, 0.82), "oak_light")
    f.block("vanity_top", (f.space.x0 + vanity_w / 2.0 + 0.05, f.space.y1 - 0.3), (vanity_w + 0.04, 0.52, 0.04), "ceramic", z=0.82)
    f.block("basin", (f.space.x0 + vanity_w / 2.0 + 0.05, f.space.y1 - 0.3), (vanity_w * 0.6, 0.3, 0.03), "ceramic", z=0.85, blocks=False)
    f.block("mirror", (f.space.x0 + vanity_w / 2.0 + 0.05, f.space.y1 - 0.04), (vanity_w * 0.8, 0.03, 0.8), "mirror", z=1.15, blocks=False)

    wc_x = f.space.x0 + 0.35
    wc_y = f.space.y0 + 0.45
    f.block("wc_pan", (wc_x, wc_y), (0.38, 0.52, 0.42), "ceramic")
    f.block("wc_cistern", (wc_x, wc_y + 0.28), (0.42, 0.18, 0.4), "ceramic", z=0.42)

    if small:
        tray = min(f.width * 0.5, 0.9)
        f.block("shower_tray", (f.space.x1 - tray / 2.0 - 0.06, f.space.y1 - tray / 2.0 - 0.06), (tray, tray, 0.06), "ceramic")
        f.block("shower_screen", (f.space.x1 - tray - 0.06, f.space.y1 - tray / 2.0 - 0.06), (0.03, tray, 1.9), "glass_clear", z=0.06, blocks=False)
    else:
        tray = min(f.width * 0.45, 1.0)
        f.block("shower_tray", (f.space.x1 - tray / 2.0 - 0.06, f.space.y1 - tray / 2.0 - 0.06), (tray, tray, 0.06), "ceramic")
        f.block("shower_screen", (f.space.x1 - tray - 0.06, f.space.y1 - tray / 2.0 - 0.06), (0.03, tray, 2.0), "glass_clear", z=0.06, blocks=False)
        f.round("shower_head", (f.space.x1 - tray / 2.0, f.space.y1 - 0.2), 0.1, 0.03, "steel", z=2.05, blocks=False)


# ------------------------------------------------------------------- entry
def _entry(f: Furnisher) -> None:
    if f.width < 1.4:
        return
    console_w = min(1.3, f.width * 0.6)
    f.block("console", (f.space.x0 + console_w / 2.0 + 0.12, f.cy), (console_w, 0.34, 0.8), "walnut")
    f.block("mirror", (f.space.x0 + 0.04, f.cy), (0.03, console_w * 0.8, 0.9), "mirror", z=1.1, blocks=False)
    f.round("vase", (f.space.x0 + console_w / 2.0 + 0.12, f.cy), 0.09, 0.3, "terracotta", z=0.8, blocks=False)


# ------------------------------------------------------------------- study
def _study(f: Furnisher) -> None:
    desk_w = min(1.5, f.width * 0.7)
    f.block("desk_top", (f.cx, f.space.y1 - 0.5), (desk_w, 0.62, 0.05), "oak", z=0.72)
    for index, dx in enumerate((-0.42, 0.42)):
        f.block(f"desk_leg_{index}", (f.cx + dx * desk_w, f.space.y1 - 0.5), (0.05, 0.56, 0.72), "metal", blocks=False)
    f.block("chair", (f.cx, f.space.y1 - 1.15), (0.46, 0.46, 0.06), "fabric_sage", z=0.44)
    f.block("chair_back", (f.cx, f.space.y1 - 0.95), (0.46, 0.06, 0.5), "fabric_sage", z=0.44)
    f.block("shelf", (f.space.x1 - 0.6, f.cy), (0.3, min(1.4, f.depth * 0.6), 0.04), "oak_light", z=1.5, blocks=False)


# ----------------------------------------------------------------- outdoor
def _outdoor(f: Furnisher) -> None:
    f.block("bench", (f.cx, f.space.y1 - 0.5), (min(1.6, f.width * 0.6), 0.42, 0.42), "oak_light")
    for index, offset in enumerate((-0.6, 0.6)):
        px = f.cx + offset * min(1.6, f.width * 0.6)
        if f.space.x0 + 0.3 < px < f.space.x1 - 0.3:
            f.round(f"planter_{index}", (px, f.space.y0 + 0.5), 0.18, 0.4, "terracotta")
            f.round(f"plant_{index}", (px, f.space.y0 + 0.5), 0.24, 0.5, "foliage", z=0.4, blocks=False)


# ------------------------------------------------------------------ utility
def _utility(f: Furnisher) -> None:
    f.block("washer", (f.space.x0 + 0.5, f.space.y0 + 0.5), (0.6, 0.6, 0.85), "steel")
    f.block("shelf", (f.cx, f.space.y1 - 0.25), (min(1.6, f.width * 0.7), 0.3, 0.04), "metal", z=1.6, blocks=False)


# ------------------------------------------------------------------- garage
def _garage(f: Furnisher) -> None:
    f.block("paving", (f.cx, f.cy), (f.width - 0.1, f.depth - 0.1, 0.02), "paving", z=0.0, blocks=False)


RECIPES = {
    "bedroom": _bedroom,
    "living": _living,
    "lounge": _living,
    "kitchen": _kitchen,
    "dining": _dining,
    "bath": _bath,
    "wc": _bath,
    "entry": _entry,
    "hall": _entry,
    "study": _study,
    "office": _study,
    "terrace": _outdoor,
    "balcony": _outdoor,
    "utility": _utility,
    "garage": _garage,
}


def furnish(space: Space, base_z: float, clear: float, glazed_sides: set[str] | None = None) -> list[Piece]:
    recipe = RECIPES.get(space.type)
    if recipe is None or space.type in ("stair", "store"):
        return []
    if space.area < 2.0:
        return []
    furnisher = Furnisher(space, base_z, clear, glazed_sides)
    recipe(furnisher)
    return furnisher.pieces
