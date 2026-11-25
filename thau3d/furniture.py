"""Procedural furniture, keyed by space type.

Everything here is a handful of boxes and cylinders placed against the walls of
a room. That is deliberate: the point of Thau3D is a *readable, walkable* model
produced in milliseconds, not a photo-real asset pack.

Crucially, placement is **wall- and door-aware**: each recipe queries the room's
doorways, door-swing clearance zones, and windows before choosing which wall to
anchor a piece against, and every furniture cluster is validated against the
room's circulation zones so a bed, TV, wardrobe, or toilet never blocks a door
or covers a window.
"""

from __future__ import annotations

from dataclasses import dataclass

from .geometry import MeshData, box, cylinder
from .spec import Space

MM = 1.0
WALL_ORDER = ("back", "left", "right", "front")


@dataclass
class Piece:
    name: str
    mesh: MeshData
    material: str
    blocks: bool = True
    group: str = ""
    plan_rect: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)


def _rects_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    margin: float = 0.0,
) -> bool:
    return (
        a[0] < b[2] + margin
        and a[2] > b[0] - margin
        and a[1] < b[3] + margin
        and a[3] > b[1] - margin
    )


def _rect_intersection_area(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    margin: float = 0.0,
) -> float:
    dx = max(0.0, min(a[2] + margin, b[2]) - max(a[0] - margin, b[0]))
    dy = max(0.0, min(a[3] + margin, b[3]) - max(a[1] - margin, b[1]))
    return dx * dy


def _interval_overlap(a0: float, a1: float, b0: float, b1: float, margin: float = 0.0) -> float:
    return max(0.0, min(a1 + margin, b1) - max(a0 - margin, b0))


class Furnisher:
    """Wall- and clearance-aware room furnisher."""

    def __init__(
        self,
        space: Space,
        base_z: float,
        clear: float,
        glazed_sides: set[str] | None = None,
        *,
        doors_by_side: dict[str, list[tuple[float, float]]] | None = None,
        windows_by_side: dict[str, list[tuple[float, float]]] | None = None,
        door_zones: list[tuple[float, float, float, float]] | None = None,
    ) -> None:
        self.space = space
        self.base = base_z
        self.clear = clear
        self.pieces: list[Piece] = []
        self.glazed = set(glazed_sides or set())
        self.doors_by_side: dict[str, list[tuple[float, float]]] = {
            side: list((doors_by_side or {}).get(side, [])) for side in WALL_ORDER
        }
        self.windows_by_side: dict[str, list[tuple[float, float]]] = {
            side: list((windows_by_side or {}).get(side, [])) for side in WALL_ORDER
        }
        for side in self.glazed:
            if side in self.windows_by_side and not self.windows_by_side[side]:
                u0, u1 = self.wall_span(side)
                mid = (u0 + u1) / 2.0
                half = (u1 - u0) * 0.28
                self.windows_by_side[side].append((mid - half, mid + half))
        self.door_zones: list[tuple[float, float, float, float]] = list(door_zones or [])
        self.group_rects: dict[str, tuple[float, float, float, float]] = {}

    @property
    def tv_at_front(self) -> bool:
        """A television belongs on a solid wall, never under a window."""
        return "front" not in self.glazed and not self.windows_by_side["front"]

    @property
    def head_at_back(self) -> bool:
        """A headboard belongs on a solid wall, never under a window."""
        return "back" not in self.glazed and not self.windows_by_side["back"]

    # -- room dimensions ----------------------------------------------------
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

    def wall_span(self, wall: str) -> tuple[float, float]:
        if wall in ("front", "back"):
            return (self.space.x0, self.space.x1)
        return (self.space.y0, self.space.y1)

    def wall_length(self, wall: str) -> float:
        u0, u1 = self.wall_span(wall)
        return u1 - u0

    def wall_depth(self, wall: str) -> float:
        """Room dimension perpendicular to ``wall``."""
        if wall in ("front", "back"):
            return self.space.depth
        return self.space.width

    def wall_to_plan(
        self,
        wall: str,
        u: float,
        v: float,
        w_along: float,
        d_perp: float,
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float, float, float]]:
        """Map wall-relative coordinates ``(u, v)`` and ``(w_along, d_perp)`` to plan space.

        ``u`` is the coordinate along ``wall`` (x for front/back, y for left/right).
        ``v`` is the perpendicular distance from ``wall`` into the room to the box center.
        """
        if wall == "front":
            cx, cy = u, self.space.y0 + v
            sx, sy = w_along, d_perp
        elif wall == "back":
            cx, cy = u, self.space.y1 - v
            sx, sy = w_along, d_perp
        elif wall == "left":
            cx, cy = self.space.x0 + v, u
            sx, sy = d_perp, w_along
        else:  # "right"
            cx, cy = self.space.x1 - v, u
            sx, sy = d_perp, w_along
        rect = (cx - sx / 2.0, cy - sy / 2.0, cx + sx / 2.0, cy + sy / 2.0)
        return (cx, cy), (sx, sy), rect

    def _record_group_rect(self, group: str, rect: tuple[float, float, float, float], blocks: bool) -> None:
        if not group or not blocks:
            return
        if group in self.group_rects:
            old = self.group_rects[group]
            self.group_rects[group] = (
                min(old[0], rect[0]),
                min(old[1], rect[1]),
                max(old[2], rect[2]),
                max(old[3], rect[3]),
            )
        else:
            self.group_rects[group] = rect

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
        group: str = "",
    ) -> None:
        """Axis-aligned box; ``z`` is the bottom height above the floor."""
        width, depth, height = size
        bottom = self.base + (z if z is not None else 0.0)
        rect = (
            center[0] - width / 2.0,
            center[1] - depth / 2.0,
            center[0] + width / 2.0,
            center[1] + depth / 2.0,
        )
        tag = group or name
        self._record_group_rect(tag, rect, blocks)
        self.pieces.append(
            Piece(
                name=name,
                mesh=box((center[0], center[1], bottom + height / 2.0), (width, depth, height)),
                material=material,
                blocks=blocks,
                group=tag,
                plan_rect=rect,
            )
        )

    def wall_block(
        self,
        wall: str,
        name: str,
        u: float,
        v: float,
        size: tuple[float, float, float],
        material: str,
        *,
        z: float | None = None,
        blocks: bool = True,
        group: str = "",
    ) -> None:
        """Place a box oriented relative to ``wall``: ``size`` is ``(w_along, d_perp, height)``."""
        w_along, d_perp, height = size
        (cx, cy), (sx, sy), _rect = self.wall_to_plan(wall, u, v, w_along, d_perp)
        self.block(name, (cx, cy), (sx, sy, height), material, z=z, blocks=blocks, group=group or name)

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
        group: str = "",
    ) -> None:
        bottom = self.base + (z if z is not None else 0.0)
        rect = (center[0] - radius, center[1] - radius, center[0] + radius, center[1] + radius)
        tag = group or name
        self._record_group_rect(tag, rect, blocks)
        self.pieces.append(
            Piece(
                name=name,
                mesh=cylinder((center[0], center[1], bottom + height / 2.0), radius, height, 16),
                material=material,
                blocks=blocks,
                group=tag,
                plan_rect=rect,
            )
        )

    def wall_round(
        self,
        wall: str,
        name: str,
        u: float,
        v: float,
        radius: float,
        height: float,
        material: str,
        *,
        z: float | None = None,
        blocks: bool = True,
        group: str = "",
    ) -> None:
        (cx, cy), _, _ = self.wall_to_plan(wall, u, v, radius * 2.0, radius * 2.0)
        self.round(name, (cx, cy), radius, height, material, z=z, blocks=blocks, group=group or name)

    def rug(self, width: float, depth: float, center: tuple[float, float] | None = None) -> None:
        pos = center or (self.cx, self.cy)
        self.block("rug", pos, (width, depth, 0.012), "rug", z=0.0, blocks=False, group="rug")

    # -- solver for wall-anchored furniture ---------------------------------
    def placement_cost(
        self,
        wall: str,
        u: float,
        w_along: float,
        d_perp: float,
        *,
        v_offset: float = 0.04,
        avoid_windows: bool = True,
        ignore_group: str = "",
    ) -> float:
        u0, u1 = self.wall_span(wall)
        half = w_along / 2.0
        if u - half < u0 + 0.06 or u + half > u1 - 0.06:
            return 1e6
        if d_perp + v_offset > self.wall_depth(wall) - 0.35:
            return 1e6

        _, _, rect = self.wall_to_plan(wall, u, v_offset + d_perp / 2.0, w_along, d_perp)
        cost = 0.0

        # Never block a door opening on this wall
        for d0, d1 in self.doors_by_side.get(wall, []):
            overlap = _interval_overlap(u - half, u + half, d0, d1, margin=0.14)
            if overlap > 0:
                cost += 5000.0 + overlap * 4000.0

        # Never intrude into any doorway swing/approach zone
        for zone in self.door_zones:
            area = _rect_intersection_area(rect, zone, margin=0.06)
            if area > 0:
                cost += 4000.0 + area * 3000.0

        # Never collide with already-placed blocking furniture groups
        for group_name, existing in self.group_rects.items():
            if group_name == ignore_group:
                continue
            area = _rect_intersection_area(rect, existing, margin=0.16)
            if area > 0:
                cost += 2500.0 + area * 2000.0

        # Avoid placing tall/backed items over a window
        if avoid_windows:
            for w0, w1 in self.windows_by_side.get(wall, []):
                overlap = _interval_overlap(u - half, u + half, w0, w1, margin=0.08)
                if overlap > 0:
                    cost += 450.0 + overlap * 400.0
            if wall in self.glazed and not self.windows_by_side.get(wall):
                cost += 350.0

        # Slight preference for walls that have no doors at all
        if self.doors_by_side.get(wall):
            cost += 12.0

        # Slight preference for centering along the wall
        mid = (u0 + u1) / 2.0
        cost += abs(u - mid) * 1.5
        return cost

    def find_wall_placement(
        self,
        w_along: float,
        d_perp: float,
        *,
        v_offset: float = 0.04,
        avoid_windows: bool = True,
        prefer_walls: tuple[str, ...] = WALL_ORDER,
        exclude_walls: set[str] | None = None,
        ignore_group: str = "",
    ) -> tuple[str, float]:
        excluded = exclude_walls or set()
        best_wall = prefer_walls[0]
        best_u = sum(self.wall_span(best_wall)) / 2.0
        best_cost = float("inf")

        for rank, wall in enumerate(prefer_walls):
            if wall in excluded:
                continue
            u0, u1 = self.wall_span(wall)
            lo = u0 + w_along / 2.0 + 0.10
            hi = u1 - w_along / 2.0 - 0.10
            if hi < lo:
                continue
            mid = (u0 + u1) / 2.0
            candidates = [mid]
            cursor = lo
            while cursor <= hi + 1e-6:
                candidates.append(min(hi, cursor))
                cursor += 0.14
            for u in candidates:
                cost = (
                    self.placement_cost(
                        wall,
                        u,
                        w_along,
                        d_perp,
                        v_offset=v_offset,
                        avoid_windows=avoid_windows,
                        ignore_group=ignore_group,
                    )
                    + rank * 2.5
                )
                if cost < best_cost:
                    best_cost = cost
                    best_wall = wall
                    best_u = u
        return best_wall, best_u


# ---------------------------------------------------------------- bedrooms
def _bedroom(f: Furnisher) -> None:
    bed_w = min(1.65, max(1.2, f.width * 0.40))
    bed_d = min(2.05, max(1.82, min(f.width, f.depth) * 0.46))

    # Pick the cleanest wall for the headboard (no door, no window, room for bed depth)
    wall, bed_u = f.find_wall_placement(
        bed_w + 0.16,
        bed_d + 0.14,
        avoid_windows=True,
        prefer_walls=("back", "left", "right", "front"),
        ignore_group="bed",
    )

    f.wall_block(wall, "bed_headboard", bed_u, 0.08, (bed_w + 0.16, 0.09, 1.08), "walnut", z=0.0, group="bed")
    bed_v = 0.12 + bed_d / 2.0
    f.wall_block(wall, "bed_base", bed_u, bed_v, (bed_w, bed_d, 0.32), "oak", z=0.06, group="bed")
    f.wall_block(wall, "bed_mattress", bed_u, bed_v, (bed_w - 0.08, bed_d - 0.08, 0.24), "linen", z=0.38, group="bed")
    f.wall_block(wall, "bed_duvet", bed_u, bed_v + 0.16, (bed_w - 0.02, bed_d - 0.58, 0.10), "bedding", z=0.62, group="bed")
    f.wall_block(
        wall,
        "bed_throw",
        bed_u,
        bed_v + bed_d / 2.0 - 0.30,
        (bed_w - 0.02, 0.48, 0.08),
        "throw",
        z=0.66,
        group="bed",
    )
    for index, offset in enumerate((-0.26, 0.26)):
        f.wall_block(
            wall,
            f"bed_pillow_{index}",
            bed_u + offset * bed_w,
            0.36,
            (bed_w * 0.40, 0.32, 0.13),
            "linen",
            z=0.62,
            group="bed",
        )

    # Nightstands on either side of the headboard if clear of doors and corners
    for side, side_sign in (("l", -1.0), ("r", 1.0)):
        nu = bed_u + side_sign * (bed_w / 2.0 + 0.32)
        group_id = f"nightstand_{side}"
        if f.placement_cost(wall, nu, 0.42, 0.40, avoid_windows=False, ignore_group=group_id) < 400.0:
            f.wall_block(wall, f"nightstand_{side}", nu, 0.24, (0.40, 0.36, 0.52), "oak", group=group_id)
            f.wall_round(wall, f"nightstand_lamp_{side}", nu, 0.24, 0.09, 0.28, "led", z=0.55, blocks=False, group=group_id)
            f.wall_block(wall, f"nightstand_stem_{side}", nu, 0.24, (0.03, 0.03, 0.16), "metal", z=0.52, blocks=False, group=group_id)

    # Wardrobe on a different clear wall span, never colliding with the bed or doors
    wardrobe_w = min(1.65, max(1.05, min(f.width, f.depth) * 0.38))
    other_walls = tuple(w for w in ("left", "right", "back", "front") if w != wall) + (wall,)
    w_wall, w_u = f.find_wall_placement(
        wardrobe_w,
        0.58,
        avoid_windows=True,
        prefer_walls=other_walls,
        ignore_group="wardrobe",
    )
    if f.placement_cost(w_wall, w_u, wardrobe_w, 0.58, avoid_windows=True, ignore_group="wardrobe") < 800.0:
        f.wall_block(w_wall, "wardrobe", w_u, 0.32, (wardrobe_w, 0.56, 2.22), "oak_light", group="wardrobe")
        f.wall_block(
            w_wall,
            "wardrobe_gap",
            w_u,
            0.61,
            (wardrobe_w - 0.10, 0.02, 2.04),
            "walnut",
            z=0.10,
            blocks=False,
            group="wardrobe",
        )

    (rug_x, rug_y), (rug_sx, rug_sy), _ = f.wall_to_plan(
        wall,
        bed_u,
        min(f.wall_depth(wall) * 0.52, bed_v + 0.35),
        min(2.4, f.wall_length(wall) * 0.65),
        min(1.85, f.wall_depth(wall) * 0.42),
    )
    f.rug(rug_sx, rug_sy, center=(rug_x, rug_y))


# ------------------------------------------------------------------ living
def _living(f: Furnisher) -> None:
    # Choose the best solid wall for the media console & TV so the sofa can sit
    # opposite it with a clear circulation path behind or alongside.
    tv_w = min(1.85, max(1.25, min(f.width, f.depth) * 0.44))
    wall, tv_u = f.find_wall_placement(
        tv_w,
        0.44,
        avoid_windows=True,
        prefer_walls=("left", "right", "back", "front"),
        ignore_group="tv",
    )

    room_d = f.wall_depth(wall)
    sofa_w = min(2.35, max(1.65, min(f.wall_length(wall) * 0.54, 2.35)))
    # Place the sofa facing the TV at a comfortable viewing distance (2.4 - 3.0 m),
    # leaving a walkway behind the sofa whenever the room is deep enough.
    sofa_v = min(room_d - 0.68, max(2.15, min(2.85, room_d * 0.66)))
    table_v = (0.48 + sofa_v - 0.45) / 2.0 + 0.15

    f.wall_block(wall, "media_console", tv_u, 0.25, (tv_w, 0.40, 0.46), "walnut", group="tv")
    f.wall_block(wall, "tv_panel", tv_u, 0.12, (min(1.42, tv_w * 0.82), 0.06, 0.80), "appliance", z=0.86, blocks=False, group="tv")

    f.wall_block(wall, "coffee_table", tv_u, table_v, (min(1.18, sofa_w * 0.56), 0.58, 0.06), "oak_light", z=0.38, group="coffee_table")
    half_tw = min(1.18, sofa_w * 0.56) * 0.40
    for index, (du, dv) in enumerate(((-half_tw, -0.22), (half_tw, -0.22), (-half_tw, 0.22), (half_tw, 0.22))):
        f.wall_block(
            wall,
            f"coffee_table_leg_{index}",
            tv_u + du,
            table_v + dv,
            (0.05, 0.05, 0.38),
            "metal",
            blocks=False,
            group="coffee_table",
        )

    # Sofa facing the TV wall (so its backrest is at sofa_v + 0.34, away from the TV wall)
    f.wall_block(wall, "sofa_base", tv_u, sofa_v, (sofa_w, 0.88, 0.42), "fabric_ivory", z=0.0, group="sofa")
    f.wall_block(wall, "sofa_back", tv_u, sofa_v + 0.34, (sofa_w, 0.20, 0.82), "fabric_ivory", z=0.0, group="sofa")
    f.wall_block(wall, "sofa_seat", tv_u, sofa_v - 0.08, (sofa_w - 0.16, 0.70, 0.14), "linen_dark", z=0.42, group="sofa")
    for index, offset in enumerate((-0.24, 0.24)):
        f.wall_block(
            wall,
            f"sofa_cushion_{index}",
            tv_u + offset * sofa_w,
            sofa_v + 0.18,
            (0.38, 0.14, 0.38),
            "fabric_sage" if index else "fabric_clay",
            z=0.56,
            group="sofa",
        )
    for side, side_sign in (("l", -1.0), ("r", 1.0)):
        f.wall_block(
            wall,
            f"sofa_arm_{side}",
            tv_u + side_sign * sofa_w / 2.0,
            sofa_v,
            (0.14, 0.88, 0.62),
            "fabric_ivory",
            z=0.0,
            group="sofa",
        )

    (rug_x, rug_y), (rug_sx, rug_sy), _ = f.wall_to_plan(
        wall,
        tv_u,
        table_v + 0.15,
        min(2.6, sofa_w + 0.4),
        min(2.0, max(1.3, sofa_v - 0.65)),
    )
    f.rug(rug_sx, rug_sy, center=(rug_x, rug_y))


# ----------------------------------------------------------------- kitchen
def _kitchen(f: Furnisher) -> None:
    # Counter can sit under a window (base counter height 0.91 m is below normal sills),
    # so pick the longest door-free wall for the main counter run.
    counter_wall = "back"
    best_score = float("inf")
    for candidate in ("back", "left", "right", "front"):
        doors = len(f.doors_by_side.get(candidate, []))
        score = doors * 100.0 - f.wall_length(candidate)
        if score < best_score:
            best_score = score
            counter_wall = candidate

    u0, u1 = f.wall_span(counter_wall)
    wall_len = u1 - u0
    run_w = min(wall_len - 0.32, max(1.6, wall_len * 0.78))
    # Leave room at one end for the fridge if the wall is long enough
    fridge_w = 0.72
    has_window_on_counter = bool(f.windows_by_side.get(counter_wall)) or (counter_wall in f.glazed)
    counter_u = (u0 + u1) / 2.0 - (fridge_w * 0.45 if wall_len > 2.8 else 0.0)
    counter_u = max(u0 + run_w / 2.0 + 0.12, min(u1 - run_w / 2.0 - 0.12, counter_u))

    f.wall_block(counter_wall, "base_cabinets", counter_u, 0.32, (run_w, 0.60, 0.86), "oak_light", group="counter")
    f.wall_block(counter_wall, "worktop", counter_u, 0.33, (run_w + 0.04, 0.64, 0.05), "quartz", z=0.86, group="counter")

    # Only add full-width backsplash and high wall cabinets if this wall has no window;
    # otherwise keep the window completely clear and put wall cabinets on an adjacent solid wall.
    if not has_window_on_counter:
        f.wall_block(
            counter_wall,
            "backsplash",
            counter_u,
            0.05,
            (run_w, 0.04, 0.55),
            "ceramic",
            z=0.91,
            blocks=False,
            group="counter",
        )
        f.wall_block(
            counter_wall,
            "wall_cabinets",
            counter_u,
            0.20,
            (run_w - 0.16, 0.36, 0.68),
            "oak_light",
            z=1.55,
            blocks=False,
            group="counter",
        )

    sink_u = counter_u - run_w * 0.22
    f.wall_block(counter_wall, "sink", sink_u, 0.32, (0.54, 0.42, 0.04), "steel", z=0.87, blocks=False, group="counter")
    f.wall_block(counter_wall, "tap", sink_u, 0.12, (0.04, 0.04, 0.28), "metal", z=0.91, blocks=False, group="counter")

    hob_u = counter_u + run_w * 0.24
    f.wall_block(counter_wall, "hob", hob_u, 0.32, (0.58, 0.48, 0.02), "appliance", z=0.91, blocks=False, group="counter")

    # Place the tall fridge against a window-free, door-free spot
    f_wall, f_u = f.find_wall_placement(
        fridge_w + 0.08,
        0.70,
        avoid_windows=True,
        prefer_walls=(counter_wall, "right", "left", "back", "front"),
        ignore_group="fridge",
    )
    if f.placement_cost(f_wall, f_u, fridge_w + 0.08, 0.70, avoid_windows=True, ignore_group="fridge") < 800.0:
        f.wall_block(f_wall, "fridge", f_u, 0.37, (fridge_w, 0.68, 1.92), "steel", group="fridge")

    # Optional breakfast island in larger kitchens when clear of doorways
    if f.wall_length(counter_wall) > 3.4 and f.wall_depth(counter_wall) > 3.3:
        island_w = min(1.85, run_w * 0.62)
        island_v = min(f.wall_depth(counter_wall) - 1.15, 2.05)
        if f.placement_cost(
            counter_wall,
            counter_u,
            island_w,
            0.88,
            v_offset=island_v - 0.44,
            avoid_windows=False,
            ignore_group="island",
        ) < 400.0:
            f.wall_block(counter_wall, "island", counter_u, island_v, (island_w, 0.82, 0.90), "oak_light", group="island")
            f.wall_block(
                counter_wall,
                "island_top",
                counter_u,
                island_v,
                (island_w + 0.06, 0.88, 0.05),
                "quartz",
                z=0.90,
                group="island",
            )
            for index, offset in enumerate((-island_w * 0.26, island_w * 0.26)):
                f.wall_block(
                    counter_wall,
                    f"stool_{index}",
                    counter_u + offset,
                    island_v + 0.66,
                    (0.34, 0.34, 0.62),
                    "fabric_clay",
                    group="island",
                )


# ------------------------------------------------------------------ dining
def _dining(f: Furnisher) -> None:
    table_w = min(1.75, f.width * 0.52)
    table_d = min(0.92, f.depth * 0.36)
    f.block("table_top", (f.cx, f.cy), (table_w, table_d, 0.06), "oak", z=0.70, group="dining_table")
    for index, (dx, dy) in enumerate(((-0.42, -0.36), (0.42, -0.36), (-0.42, 0.36), (0.42, 0.36))):
        f.block(
            f"table_leg_{index}",
            (f.cx + dx * table_w, f.cy + dy * table_d),
            (0.06, 0.06, 0.70),
            "metal",
            blocks=False,
            group="dining_table",
        )
    chair_offsets = (
        (-0.26, -0.68, "n"),
        (0.26, -0.68, "n"),
        (-0.26, 0.68, "s"),
        (0.26, 0.68, "s"),
    )
    for index, (dx, dy, _side) in enumerate(chair_offsets):
        chair_x = f.cx + dx * table_w
        chair_y = f.cy + dy
        if not (f.space.y0 + 0.35 < chair_y < f.space.y1 - 0.35):
            continue
        f.block(f"chair_{index}", (chair_x, chair_y), (0.42, 0.42, 0.05), "oak_light", z=0.44, group="dining_table")
        f.block(
            f"chair_back_{index}",
            (chair_x, chair_y + (0.19 if dy > 0 else -0.19)),
            (0.42, 0.05, 0.45),
            "oak_light",
            z=0.44,
            group="dining_table",
        )
        for leg in (-1, 1):
            f.block(
                f"chair_leg_{index}_{leg}",
                (chair_x + leg * 0.17, chair_y),
                (0.04, 0.40, 0.44),
                "metal",
                blocks=False,
                group="dining_table",
            )
    f.rug(min(2.5, table_w + 0.85), min(2.0, table_d + 1.05))


# -------------------------------------------------------------------- bath
def _bath(f: Furnisher) -> None:
    vanity_w = min(0.86, max(0.58, min(f.width, f.depth) * 0.44))
    v_wall, v_u = f.find_wall_placement(
        vanity_w,
        0.50,
        avoid_windows=True,
        prefer_walls=("back", "right", "left", "front"),
        ignore_group="vanity",
    )
    f.wall_block(v_wall, "vanity", v_u, 0.27, (vanity_w, 0.48, 0.82), "oak_light", group="vanity")
    f.wall_block(v_wall, "vanity_top", v_u, 0.28, (vanity_w + 0.04, 0.52, 0.04), "ceramic", z=0.82, group="vanity")
    f.wall_block(v_wall, "basin", v_u, 0.28, (vanity_w * 0.58, 0.30, 0.03), "ceramic", z=0.85, blocks=False, group="vanity")
    f.wall_block(v_wall, "mirror", v_u, 0.03, (vanity_w * 0.82, 0.03, 0.82), "mirror", z=1.12, blocks=False, group="vanity")

    wc_wall, wc_u = f.find_wall_placement(
        0.48,
        0.64,
        avoid_windows=False,
        prefer_walls=("right", "left", "back", "front"),
        ignore_group="wc",
    )
    f.wall_block(wc_wall, "wc_pan", wc_u, 0.36, (0.38, 0.52, 0.42), "ceramic", group="wc")
    f.wall_block(wc_wall, "wc_cistern", wc_u, 0.12, (0.42, 0.18, 0.40), "ceramic", z=0.42, group="wc")

    tray = min(0.92, min(f.width, f.depth) * 0.42)
    s_wall, s_u = f.find_wall_placement(
        tray,
        tray,
        avoid_windows=False,
        prefer_walls=("back", "right", "left", "front"),
        ignore_group="shower",
    )
    if f.placement_cost(s_wall, s_u, tray, tray, avoid_windows=False, ignore_group="shower") < 1200.0:
        f.wall_block(s_wall, "shower_tray", s_u, tray / 2.0 + 0.05, (tray, tray, 0.05), "ceramic", blocks=False, group="shower")
        f.wall_block(
            s_wall,
            "shower_screen",
            s_u,
            tray + 0.04,
            (tray * 0.88, 0.03, 1.95),
            "glass_clear",
            z=0.05,
            blocks=False,
            group="shower",
        )
        f.wall_round(s_wall, "shower_head", s_u, 0.22, 0.10, 0.03, "steel", z=2.05, blocks=False, group="shower")


# ------------------------------------------------------------------- study
def _study(f: Furnisher) -> None:
    desk_w = min(1.45, max(1.0, min(f.width, f.depth) * 0.48))
    wall, u = f.find_wall_placement(
        desk_w,
        1.25,
        avoid_windows=False,
        prefer_walls=("back", "left", "right", "front"),
        ignore_group="desk",
    )
    f.wall_block(wall, "desk_top", u, 0.38, (desk_w, 0.62, 0.05), "oak", z=0.72, group="desk")
    for index, du in enumerate((-0.42, 0.42)):
        f.wall_block(wall, f"desk_leg_{index}", u + du * desk_w, 0.38, (0.05, 0.56, 0.72), "metal", blocks=False, group="desk")
    f.wall_block(wall, "chair", u, 0.98, (0.46, 0.46, 0.06), "fabric_sage", z=0.44, group="desk")
    f.wall_block(wall, "chair_back", u, 1.18, (0.46, 0.06, 0.50), "fabric_sage", z=0.44, group="desk")
    # A desk lamp is what makes a study look used rather than staged.
    f.wall_round(wall, "desk_lamp", u + desk_w * 0.34, 0.30, 0.07, 0.26, "led", z=0.77, blocks=False, group="desk")
    f.wall_block(wall, "desk_lamp_stem", u + desk_w * 0.34, 0.30, (0.03, 0.03, 0.10), "metal", z=0.77, blocks=False, group="desk")

    # Full-height bookcase on a solid wall, clear of doors and windows.
    book_w = min(1.6, max(1.0, min(f.width, f.depth) * 0.42))
    b_wall, b_u = f.find_wall_placement(
        book_w,
        0.34,
        avoid_windows=True,
        prefer_walls=("left", "right", "back", "front"),
        ignore_group="bookcase",
    )
    if f.placement_cost(b_wall, b_u, book_w, 0.34, avoid_windows=True, ignore_group="bookcase") < 900.0:
        f.wall_block(b_wall, "bookcase", b_u, 0.19, (book_w, 0.32, 2.05), "oak_light", group="bookcase")
        for index in range(4):
            f.wall_block(
                b_wall,
                f"bookcase_shelf_{index}",
                b_u,
                0.19,
                (book_w - 0.08, 0.02, 0.03),
                "walnut",
                z=0.36 + index * 0.42,
                blocks=False,
                group="bookcase",
            )
            for side in (-1, 1):
                f.wall_block(
                    b_wall,
                    f"book_row_{index}_{side}",
                    b_u + side * book_w * 0.24,
                    0.16,
                    (book_w * 0.34, 0.20, 0.24),
                    "fabric_clay" if index % 2 else "fabric_sage",
                    z=0.40 + index * 0.42,
                    blocks=False,
                    group="bookcase",
                )

    # Reading chair in a corner, only if it does not crowd a doorway.
    chair_wall, chair_u = f.find_wall_placement(
        0.8, 0.8, avoid_windows=False, prefer_walls=("right", "left", "back", "front"), ignore_group="reading"
    )
    if f.placement_cost(chair_wall, chair_u, 0.8, 0.8, avoid_windows=False, ignore_group="reading") < 900.0:
        f.wall_block(chair_wall, "reading_chair", chair_u, 0.52, (0.68, 0.68, 0.40), "fabric_clay", group="reading")
        f.wall_block(chair_wall, "reading_chair_back", chair_u, 0.84, (0.68, 0.14, 0.72), "fabric_clay", z=0.40, group="reading")
        f.wall_round(chair_wall, "reading_lamp", chair_u + 0.62, 0.52, 0.11, 0.34, "led", z=1.45, blocks=False, group="reading")
        f.wall_block(chair_wall, "reading_lamp_stem", chair_u + 0.62, 0.52, (0.03, 0.03, 1.10), "metal", z=0.35, blocks=False, group="reading")

    f.rug(min(2.6, f.width * 0.55), min(2.0, f.depth * 0.42))


# ------------------------------------------------------------------- entry
def _entry(f: Furnisher) -> None:
    if min(f.width, f.depth) < 1.35:
        return
    console_w = min(1.15, max(0.75, min(f.width, f.depth) * 0.44))
    wall, u = f.find_wall_placement(
        console_w,
        0.34,
        avoid_windows=True,
        prefer_walls=("right", "left", "back", "front"),
        ignore_group="console",
    )
    if f.placement_cost(wall, u, console_w, 0.34, avoid_windows=True, ignore_group="console") > 500.0:
        return
    f.wall_block(wall, "console", u, 0.19, (console_w, 0.32, 0.80), "walnut", group="console")
    f.wall_block(wall, "mirror", u, 0.03, (console_w * 0.78, 0.03, 0.90), "mirror", z=1.08, blocks=False, group="console")
    f.wall_round(wall, "vase", u - console_w * 0.28, 0.19, 0.08, 0.28, "terracotta", z=0.80, blocks=False, group="console")
    f.wall_block(wall, "entry_tray", u + console_w * 0.26, 0.19, (0.22, 0.16, 0.03), "brass", z=0.80, blocks=False, group="console")

    # Bench to sit on while you take your shoes off, on an adjacent clear wall.
    bench_w = min(0.95, max(0.6, min(f.width, f.depth) * 0.38))
    b_wall, b_u = f.find_wall_placement(
        bench_w, 0.36, avoid_windows=True, prefer_walls=("left", "right", "back", "front"), ignore_group="bench"
    )
    if f.placement_cost(b_wall, b_u, bench_w, 0.36, avoid_windows=True, ignore_group="bench") < 800.0:
        f.wall_block(b_wall, "shoe_bench", b_u, 0.20, (bench_w, 0.36, 0.44), "oak_light", group="bench")
        f.wall_block(b_wall, "shoe_shelf", b_u, 0.20, (bench_w - 0.08, 0.30, 0.03), "metal", z=0.14, blocks=False, group="bench")

    f.wall_block(wall, "coat_hooks", u + console_w * 0.5, 0.05, (0.55, 0.04, 0.06), "brass", z=1.62, blocks=False, group="console")
    f.rug(min(1.4, f.width * 0.5), min(0.9, f.depth * 0.28))


# -------------------------------------------------------------------- hall
def _hall(f: Furnisher) -> None:
    """A landing or hall: barely furnished, but never bare.

    A landing is mostly circulation, so it gets a plant in whichever corner is
    furthest from a doorway plus a runner. The solver still chooses the corner;
    the doorway filter removes the plant outright if every corner is a doorway.
    """
    if min(f.width, f.depth) >= 1.3:
        wall, u = f.find_wall_placement(
            0.55, 0.55, avoid_windows=False, prefer_walls=("back", "left", "right", "front"), ignore_group="plant"
        )
        f.wall_round(wall, "plant_pot", u, 0.30, 0.17, 0.40, "terracotta", group="plant")
        f.wall_round(wall, "plant", u, 0.30, 0.24, 0.52, "foliage", z=0.40, blocks=False, group="plant")
    f.rug(min(1.8, f.width * 0.6), min(1.2, f.depth * 0.4))


# ----------------------------------------------------------------- outdoor
def _outdoor(f: Furnisher) -> None:
    bench_w = min(1.5, max(0.9, min(f.width, f.depth) * 0.48))
    wall, u = f.find_wall_placement(bench_w, 0.46, avoid_windows=False, ignore_group="bench")
    f.wall_block(wall, "bench", u, 0.30, (bench_w, 0.42, 0.42), "oak_light", group="bench")
    for index, offset in enumerate((-0.72, 0.72)):
        pu = u + offset * bench_w
        u0, u1 = f.wall_span(wall)
        if u0 + 0.32 < pu < u1 - 0.32:
            f.wall_round(wall, f"planter_{index}", pu, 0.32, 0.18, 0.40, "terracotta", group=f"planter_{index}")
            f.wall_round(wall, f"plant_{index}", pu, 0.32, 0.24, 0.50, "foliage", z=0.40, blocks=False, group=f"planter_{index}")


# ------------------------------------------------------------------ utility
def _utility(f: Furnisher) -> None:
    wall, u = f.find_wall_placement(0.65, 0.65, avoid_windows=False, ignore_group="washer")
    f.wall_block(wall, "washer", u, 0.36, (0.60, 0.60, 0.85), "steel", group="washer")
    f.wall_block(wall, "shelf", u, 0.18, (min(1.4, f.wall_length(wall) * 0.6), 0.30, 0.04), "metal", z=1.55, blocks=False, group="washer")


# ------------------------------------------------------------------- garage
def _garage(f: Furnisher) -> None:
    f.block("paving", (f.cx, f.cy), (f.width - 0.1, f.depth - 0.1, 0.02), "paving", z=0.0, blocks=False, group="paving")


RECIPES = {
    "bedroom": _bedroom,
    "living": _living,
    "lounge": _living,
    "kitchen": _kitchen,
    "dining": _dining,
    "bath": _bath,
    "wc": _bath,
    "entry": _entry,
    "hall": _hall,
    "landing": _hall,
    "study": _study,
    "office": _study,
    "terrace": _outdoor,
    "balcony": _outdoor,
    "utility": _utility,
    "garage": _garage,
}


def furnish(
    space: Space,
    base_z: float,
    clear: float,
    glazed_sides: set[str] | None = None,
    *,
    doors_by_side: dict[str, list[tuple[float, float]]] | None = None,
    windows_by_side: dict[str, list[tuple[float, float]]] | None = None,
    door_zones: list[tuple[float, float, float, float]] | None = None,
) -> list[Piece]:
    recipe = RECIPES.get(space.type)
    if recipe is None or space.type in ("stair", "store"):
        return []
    if space.area < 2.0:
        return []
    furnisher = Furnisher(
        space,
        base_z,
        clear,
        glazed_sides,
        doors_by_side=doors_by_side,
        windows_by_side=windows_by_side,
        door_zones=door_zones,
    )
    recipe(furnisher)

    # Final group-level safety filter. The solver already steers furniture away
    # from doors; this only removes a group that still sits squarely in a doorway.
    if furnisher.door_zones:
        bad_groups: set[str] = set()
        for group_name, rect in furnisher.group_rects.items():
            for zone in furnisher.door_zones:
                if _rect_intersection_area(rect, zone, margin=0.0) > 0.25:
                    bad_groups.add(group_name)
                    break
        if bad_groups:
            return [piece for piece in furnisher.pieces if piece.group not in bad_groups]
    return furnisher.pieces
