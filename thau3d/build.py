"""Spec -> walkable GLB.

The builder is deterministic: the same spec always produces the same geometry,
in the same order, with the same node names. That is what lets an agent diff two
builds and know whether its edit did what it meant.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .furniture import furnish
from .geometry import MeshData, box, box_xyz, wedge
from .glb import GLB
from .materials import resolve_overrides
from .spec import Building, Space, Stair, Storey, balcony_rect, stair_flight

EYE_HEIGHT = 1.62

# Room role categories used when deriving interior doors and open passages.
HALL_TYPES = {"hall", "landing", "entry"}
OPEN_DAY_TYPES = {"hall", "landing", "entry", "living", "lounge", "dining", "kitchen"}
PRIVATE_TYPES = {"bedroom", "bath", "wc", "study", "office", "utility", "store"}
CIRCULATION_TYPES = {"hall", "landing", "entry", "stair", "living", "lounge", "dining", "kitchen", "office"}

# A door between these pairs is always refused unless explicitly forced.
NO_DOOR_PAIRS = {
    ("kitchen", "bath"),
    ("kitchen", "wc"),
    ("dining", "bath"),
    ("dining", "wc"),
    ("living", "bath"),
    ("living", "wc"),
}
EPS = 1e-4


@dataclass
class BuildReport:
    nodes: int = 0
    triangles: int = 0
    bytes: int = 0
    materials: int = 0
    spaces: list[dict] = field(default_factory=list)
    storeys: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    glb: Path | None = None
    manifest: Path | None = None
    manifest_data: dict = field(default_factory=dict)

    def summary(self) -> str:
        lines = [
            f"built {self.glb.name if self.glb else '?'}",
            f"  {self.nodes} nodes · {self.triangles:,} triangles · {self.bytes / 1024:.0f} KB · {self.materials} materials",
        ]
        for storey in self.storeys:
            lines.append(
                f"  {storey['id']}: {storey['spaces']} spaces · {storey['area_net']:.1f} m² net"
            )
        for warning in self.warnings:
            lines.append(f"  warning: {warning}")
        return "\n".join(lines)


# --------------------------------------------------------------------- maths
def _bounds(positions: list[tuple[float, float, float]]) -> tuple[list[float], list[float]]:
    xs = [p[0] for p in positions]
    ys = [p[1] for p in positions]
    zs = [p[2] for p in positions]
    return ([min(xs), min(ys), min(zs)], [max(xs), max(ys), max(zs)])


def _rects_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    margin: float = 0.02,
) -> bool:
    return (
        a[0] < b[2] - margin
        and a[2] > b[0] + margin
        and a[1] < b[3] - margin
        and a[3] > b[1] + margin
    )


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return min(a1, b1) - max(a0, b0)


class Builder:
    def __init__(self, building: Building) -> None:
        self.b = building
        self.glb = GLB()
        self.palette = resolve_overrides(building.palette_overrides)
        self.colliders: list[dict] = []
        self.supports: list[dict] = []
        self.luminaires: list[dict] = []
        self.spaces_manifest: list[dict] = []
        self.stairs_manifest: list[dict] = []
        self.balconies_manifest: list[dict] = []
        self.door_clearance: dict[str, list[tuple[float, float, float, float]]] = {}
        self.furniture_zones: dict[str, list[tuple[float, float, float, float]]] = {}
        self.space_windows: dict[str, set[str]] = {}
        self.space_windows_by_side: dict[str, dict[str, list[tuple[float, float]]]] = {}
        self.space_doors_by_side: dict[str, dict[str, list[tuple[float, float]]]] = {}
        self._openings_cache: dict[str, dict[str, list[dict]]] = {}
        self.warnings: list[str] = []
        self._material_index: dict[str, int] = {}
        self._counters: dict[str, int] = {}

    # ------------------------------------------------------------- materials
    def mat(self, key: str) -> int:
        if key in self._material_index:
            return self._material_index[key]
        definition = self.palette.get(key)
        if definition is None:
            definition = self.palette["wall"]
        index = self.glb.material(
            key,
            color=definition.color,
            metallic=definition.metallic,
            roughness=definition.roughness,
            opacity=definition.opacity,
            emissive=definition.emissive,
            emissive_strength=definition.emissive_strength,
            double_sided=definition.double_sided,
        )
        self._material_index[key] = index
        return index

    # ---------------------------------------------------------------- naming
    def name(self, kind: str, storey_id: str = "") -> str:
        key = f"{storey_id}:{kind}" if storey_id else kind
        self._counters[key] = self._counters.get(key, 0) + 1
        prefix = f"{storey_id}__" if storey_id else ""
        return f"{prefix}{kind}_{self._counters[key]:03d}"

    # ---------------------------------------------------------------- shapes
    def emit(
        self,
        name: str,
        mesh: MeshData,
        material: str,
        storey_id: str,
        *,
        collider: str | None = None,
        support: str | None = None,
        extras: dict | None = None,
    ) -> None:
        if not mesh.indices:
            return
        payload = {"storey": storey_id} if storey_id else {}
        if extras:
            payload.update(extras)
        self.glb.add_mesh(
            name,
            mesh.positions,
            mesh.normals,
            mesh.indices,
            self.mat(material),
            extras=payload or None,
        )
        if collider:
            low, high = _bounds(mesh.positions)
            self.colliders.append({"min": low, "max": high, "tag": collider})
        if support:
            low, high = _bounds(mesh.positions)
            self.supports.append({"min": low, "max": high, "tag": support})

    def block(
        self,
        name: str,
        center: tuple[float, float, float],
        size: tuple[float, float, float],
        material: str,
        storey_id: str,
        *,
        yaw: float = 0.0,
        collider: str | None = None,
        support: str | None = None,
    ) -> None:
        self.emit(name, box(center, size, yaw), material, storey_id, collider=collider, support=support)

    # ------------------------------------------------------------------ walls
    def wall_run(
        self,
        name: str,
        a: tuple[float, float],
        b: tuple[float, float],
        thickness: float,
        base_z: float,
        height: float,
        openings: list[dict],
        material: str,
        storey_id: str,
    ) -> None:
        """A wall from ``a`` to ``b`` with rectangular openings punched through it."""
        dx = b[0] - a[0]
        dy = b[1] - a[1]
        length = math.hypot(dx, dy)
        if length < EPS or height <= 0:
            return
        ux, uy = dx / length, dy / length
        yaw = math.atan2(uy, ux)

        def segment(t0: float, t1: float, z0: float, z1: float) -> None:
            span = t1 - t0
            if span <= 1e-3 or z1 - z0 <= 1e-3:
                return
            mid = (t0 + t1) / 2.0
            cx = a[0] + ux * mid
            cy = a[1] + uy * mid
            self.block(
                self.name(name, storey_id),
                (cx, cy, base_z + (z0 + z1) / 2.0),
                (span, thickness, z1 - z0),
                material,
                storey_id,
                yaw=yaw,
                collider="wall",
            )
            # Skirting: a 10 cm band at the foot of every wall segment that meets
            # the floor. It is the shadow line that makes a room look finished.
            if z0 <= 1e-6 and material in ("wall", "wall_inner") and span > 0.25:
                self.block(
                    self.name(f"{name}_skirt", storey_id),
                    (cx, cy, base_z + 0.05),
                    (span, thickness + 0.02, 0.10),
                    "skirting",
                    storey_id,
                    yaw=yaw,
                )

        ordered = sorted(openings, key=lambda item: item["t0"])
        cursor = 0.0
        for opening in ordered:
            t0 = max(0.0, opening["t0"])
            t1 = min(length, opening["t1"])
            if t1 - t0 <= 1e-3:
                continue
            if t0 > cursor:
                segment(cursor, t0, 0.0, height)
            sill = max(0.0, opening.get("sill", 0.0))
            head = min(height, opening.get("head", height))
            if sill > 0:
                segment(t0, t1, 0.0, sill)
            if head < height:
                segment(t0, t1, head, height)
            if opening.get("glass"):
                self.glaze(name, a, (ux, uy), yaw, t0, t1, sill, head, base_z, thickness, storey_id)
            elif opening.get("frame"):
                self.frame_opening(name, a, (ux, uy), yaw, t0, t1, sill, head, base_z, thickness, storey_id)
            cursor = max(cursor, t1)
        if cursor < length:
            segment(cursor, length, 0.0, height)

    def _insert(
        self,
        a: tuple[float, float],
        direction: tuple[float, float],
        t: float,
        span: float,
        thickness: float,
        z0: float,
        z1: float,
        material: str,
        name: str,
        storey_id: str,
        yaw: float,
        collider: str | None = None,
    ) -> None:
        if span <= 1e-3 or z1 - z0 <= 1e-3:
            return
        self.block(
            self.name(name, storey_id),
            (a[0] + direction[0] * t, a[1] + direction[1] * t, (z0 + z1) / 2.0),
            (span, thickness, z1 - z0),
            material,
            storey_id,
            yaw=yaw,
            collider=collider,
        )

    def glaze(
        self,
        name: str,
        a: tuple[float, float],
        direction: tuple[float, float],
        yaw: float,
        t0: float,
        t1: float,
        sill: float,
        head: float,
        base_z: float,
        thickness: float,
        storey_id: str,
    ) -> None:
        """A window: a pane plus a slim dark frame, sitting in the wall opening."""
        bar = 0.075
        centre = (t0 + t1) / 2.0
        inner = thickness * 0.45
        self._insert(
            a, direction, centre, t1 - t0 - bar * 2, 0.02,
            base_z + sill + bar, base_z + head - bar,
            "glass", f"{name}_pane", storey_id, yaw, collider="glass",
        )
        for index, t in enumerate((t0 + bar / 2.0, t1 - bar / 2.0)):
            self._insert(
                a, direction, t, bar, inner,
                base_z + sill, base_z + head,
                "frame", f"{name}_jamb{index}", storey_id, yaw,
            )
        for label, z0, z1 in (("head", head - bar, head), ("sill", sill, sill + bar)):
            self._insert(
                a, direction, centre, t1 - t0, inner,
                base_z + z0, base_z + z1,
                "frame", f"{name}_{label}", storey_id, yaw,
            )

    def frame_opening(
        self,
        name: str,
        a: tuple[float, float],
        direction: tuple[float, float],
        yaw: float,
        t0: float,
        t1: float,
        sill: float,
        head: float,
        base_z: float,
        thickness: float,
        storey_id: str,
    ) -> None:
        """A door or archway frame: crisp dark jambs and head reveal."""
        bar = 0.055
        centre = (t0 + t1) / 2.0
        inner = thickness + 0.02
        for index, t in enumerate((t0 + bar / 2.0, t1 - bar / 2.0)):
            self._insert(
                a, direction, t, bar, inner,
                base_z + sill, base_z + head,
                "frame", f"{name}_jamb{index}", storey_id, yaw,
            )
        self._insert(
            a, direction, centre, t1 - t0, inner,
            base_z + head - bar, base_z + head,
            "frame", f"{name}_head", storey_id, yaw,
        )

    # ------------------------------------------------------------------ slab
    def slab(
        self,
        storey_id: str,
        thickness: float,
        top_z: float,
        hole: tuple[float, float, float, float] | None,
        material: str,
        support_tag: str,
    ) -> None:
        width = self.b.width
        depth = self.b.depth
        bottom = top_z - thickness

        def piece(x0: float, y0: float, x1: float, y1: float) -> None:
            if x1 - x0 < 1e-3 or y1 - y0 < 1e-3:
                return
            self.block(
                self.name("slab", storey_id),
                ((x0 + x1) / 2.0, (y0 + y1) / 2.0, bottom + thickness / 2.0),
                (x1 - x0, y1 - y0, thickness),
                material,
                storey_id,
                support=support_tag,
            )

        if hole is None:
            piece(0.0, 0.0, width, depth)
            return
        hx0, hy0, hx1, hy1 = hole
        piece(0.0, 0.0, hx0, depth)
        piece(hx1, 0.0, width, depth)
        piece(hx0, 0.0, hx1, hy0)
        piece(hx0, hy1, hx1, depth)

    # ------------------------------------------------------------------ site
    def build_site(self) -> None:
        site = self.b.site
        width = max(site["width"], self.b.width + 6.0)
        depth = max(site["depth"], self.b.depth + 8.0)
        centre_x = self.b.width / 2.0
        centre_y = self.b.depth / 2.0
        ground_y = -0.15

        surface = str(site.get("surface") or "earth").lower()
        surface_material = {
            "earth": "earth",
            "dirt": "earth",
            "soil": "earth",
            "grass": "grass",
            "lawn": "grass",
            "gravel": "gravel",
            "paving": "paving",
            "concrete": "concrete",
            "ground": "earth",
        }.get(surface, "earth")
        self.site_color = self.palette[surface_material].color

        self.block(
            "site_ground",
            (centre_x, centre_y, ground_y - 0.3),
            (width, depth, 0.6),
            surface_material,
            "",
            support="ground",
        )
        self.site_bounds = {
            "min": [centre_x - width / 2.0, ground_y - 0.6, -(centre_y + depth / 2.0)],
            "max": [centre_x + width / 2.0, ground_y, -(centre_y - depth / 2.0)],
        }

        # A concrete apron rings the building: hard edge, then grass beyond.
        apron = float(site.get("apron", 0.0))
        if apron > 0:
            top = ground_y + 0.03
            thickness = 0.16
            ring = [
                ("front", (-apron, -apron, self.b.width + apron, 0.0)),
                ("back", (-apron, self.b.depth, self.b.width + apron, self.b.depth + apron)),
                ("left", (-apron, 0.0, 0.0, self.b.depth)),
                ("right", (self.b.width, 0.0, self.b.width + apron, self.b.depth)),
            ]
            for label, (ax0, ay0, ax1, ay1) in ring:
                self.block(
                    self.name(f"apron_{label}", ""),
                    ((ax0 + ax1) / 2.0, (ay0 + ay1) / 2.0, top - thickness / 2.0),
                    (ax1 - ax0, ay1 - ay0, thickness),
                    "concrete",
                    "",
                    support="concrete",
                )

        border = float(site.get("border", 1.0))
        if border > 0:
            span_x = width / 2.0
            span_y = depth / 2.0
            edge_x0, edge_x1 = centre_x - span_x, centre_x + span_x
            edge_y0, edge_y1 = centre_y - span_y, centre_y + span_y
            thickness = 0.18
            gate = (site.get("path") or {}).get("x")
            runs = [
                ((edge_x0, edge_y1), (edge_x1, edge_y1)),
                ((edge_x0, edge_y0), (edge_x0, edge_y1)),
                ((edge_x1, edge_y0), (edge_x1, edge_y1)),
            ]
            if gate:
                gap0 = max(edge_x0 + 0.4, float(gate[0]) - 0.35)
                gap1 = min(edge_x1 - 0.4, float(gate[1]) + 0.35)
                runs.append(((edge_x0, edge_y0), (gap0, edge_y0)))
                runs.append(((gap1, edge_y0), (edge_x1, edge_y0)))
                # Stone gate piers on either side of the entrance walk
                for pier_index, pier_x in enumerate((gap0, gap1)):
                    self.block(
                        f"site_gate_pier_{pier_index}",
                        (pier_x, edge_y0, ground_y + (border + 0.18) / 2.0),
                        (0.32, 0.32, border + 0.18),
                        "stone",
                        "",
                        collider="wall",
                    )
            else:
                runs.append(((edge_x0, edge_y0), (edge_x1, edge_y0)))
            for index, (start_point, end_point) in enumerate(runs):
                self.wall_run(
                    f"site_wall_{index}",
                    start_point,
                    end_point,
                    thickness,
                    ground_y,
                    border,
                    [],
                    "stone",
                    "",
                )

        path = site.get("path") or {}
        if path:
            x = path.get("x") or [self.b.width * 0.45, self.b.width * 0.55]
            x0, x1 = float(x[0]), float(x[1])
            y0 = float(path.get("from", -(centre_y - self.b.depth / 2.0) - 0.1))
            y1 = float(path.get("to", 0.0))
            self.block(
                "site_path",
                ((x0 + x1) / 2.0, (y0 + y1) / 2.0, ground_y - 0.025),
                (x1 - x0, y1 - y0, 0.12),
                "paving",
                "",
                support="paving",
            )

    # ------------------------------------------------------------ exterior
    def _side_geometry(self) -> dict[str, tuple[tuple[float, float], tuple[float, float], int]]:
        """side -> (start, end, axis index used for 't' along the wall)."""
        width = self.b.width
        depth = self.b.depth
        return {
            "front": ((0.0, 0.0), (width, 0.0), 0),
            "back": ((0.0, depth), (width, depth), 0),
            "left": ((0.0, 0.0), (0.0, depth), 1),
            "right": ((width, 0.0), (width, depth), 1),
        }

    def _touches(self, space: Space, side: str) -> bool:
        if side == "front":
            return space.y0 <= EPS
        if side == "back":
            return space.y1 >= self.b.depth - EPS
        if side == "left":
            return space.x0 <= EPS
        return space.x1 >= self.b.width - EPS

    def _span_along(self, space: Space, side: str) -> tuple[float, float]:
        if side in ("front", "back"):
            return (space.x0, space.x1)
        return (space.y0, space.y1)

    def _record_space_opening(
        self,
        space: Space,
        side: str,
        t0: float,
        t1: float,
        *,
        is_door: bool,
    ) -> None:
        if is_door:
            self.space_doors_by_side.setdefault(space.id, {}).setdefault(side, []).append((t0, t1))
            # A balcony or entrance opening is a frame you walk through, not a
            # leaf that swings, so its approach zone is shallower than an
            # interior door's.
            clear = 0.60
            if side == "front":
                zone = (t0, space.y0, t1, min(space.y1, space.y0 + clear))
            elif side == "back":
                zone = (t0, max(space.y0, space.y1 - clear), t1, space.y1)
            elif side == "left":
                zone = (space.x0, t0, min(space.x1, space.x0 + clear), t1)
            else:
                zone = (max(space.x0, space.x1 - clear), t0, space.x1, t1)
            self.door_clearance.setdefault(space.id, []).append(zone)
        else:
            self.space_windows.setdefault(space.id, set()).add(side)
            self.space_windows_by_side.setdefault(space.id, {}).setdefault(side, []).append((t0, t1))

    def exterior_openings(self, storey: Storey) -> dict[str, list[dict]]:
        sides = self._side_geometry()
        result: dict[str, list[dict]] = {side: [] for side in sides}
        defaults = self.b.defaults
        explicit: set[tuple[str, str]] = set()

        # Balcony doors: a framed opening where each projecting balcony meets the wall
        for balcony in self.b.balconies:
            if balcony.storey != storey.id:
                continue
            side = balcony.side
            if side not in sides:
                continue
            span = balcony.span[1] - balcony.span[0]
            width = min(balcony.door, span - 0.4)
            if width <= 0.6:
                self.warnings.append(
                    f'balcony "{balcony.id}" is too narrow for a door and was skipped'
                )
                continue
            centre = (balcony.span[0] + balcony.span[1]) / 2.0
            head = min(2.35, storey.clear - 0.3)
            t0 = centre - width / 2.0
            t1 = centre + width / 2.0
            owner_id = ""
            for space in storey.spaces:
                if self._touches(space, side):
                    s0, s1 = self._span_along(space, side)
                    if _overlap(t0, t1, s0, s1) > 0.25:
                        owner_id = space.id
                        break
            result[side].append(
                {
                    "t0": t0,
                    "t1": t1,
                    "sill": 0.0,
                    "head": head,
                    "door": True,
                    "frame": True,
                    "space": owner_id,
                }
            )

        for window in self.b.windows:
            space = self.b.space(window.space, window.storey)
            if space is None or space.storey != storey.id:
                continue
            side = window.side
            if side not in sides or not self._touches(space, side):
                self.warnings.append(
                    f"window for {space.id} ignored: that space does not touch the {side} elevation"
                )
                continue
            start, end = self._span_along(space, side)
            centre = (start + end) / 2.0 + window.offset
            width = min(window.width, (end - start) - 0.2)
            if width <= 0.2:
                continue
            t0 = max(start + 0.1, min(end - width - 0.1, centre - width / 2.0))
            result[side].append(
                {
                    "t0": t0,
                    "t1": t0 + width,
                    "sill": window.sill,
                    "head": window.head,
                    "glass": True,
                    "space": space.id,
                }
            )
            explicit.add((space.id, side))

        # Main entrance door
        entrance = self.b.entrance
        if entrance["space"]:
            space = self.b.space(entrance["space"])
            if space is not None and space.storey == storey.id and storey.index == 0:
                side = entrance["side"]
                if side in sides and self._touches(space, side):
                    start, end = self._span_along(space, side)
                    width = min(entrance["width"], (end - start) - 0.2)
                    centre = (start + end) / 2.0 + entrance.get("offset", 0.0)
                    centre = min(max(centre, start + width / 2.0 + 0.1), end - width / 2.0 - 0.1)
                    result[side].append(
                        {
                            "t0": centre - width / 2.0,
                            "t1": centre + width / 2.0,
                            "sill": 0.0,
                            "head": entrance["height"],
                            "door": True,
                            "entrance": True,
                            "frame": True,
                            "space": space.id,
                        }
                    )

        # Automatic windows so a plain spec still yields a daylit house
        for space in storey.spaces:
            if space.type not in ("living", "bedroom", "kitchen", "dining", "study", "office", "lounge"):
                continue
            candidates = [side for side in sides if self._touches(space, side)]
            if not candidates:
                continue
            side = "front" if "front" in candidates else candidates[0]
            if (space.id, side) in explicit:
                continue
            start, end = self._span_along(space, side)
            span = end - start
            if span < 1.2:
                continue
            width = min(span * 0.62, 2.6)
            centre = (start + end) / 2.0
            result[side].append(
                {
                    "t0": centre - width / 2.0,
                    "t1": centre + width / 2.0,
                    "sill": defaults["windowSill"],
                    "head": min(defaults["windowHead"], storey.clear - 0.3),
                    "glass": True,
                    "space": space.id,
                }
            )

        for side, openings in result.items():
            # Doors win: a balcony or entrance opening is structural, a window can yields
            clean: list[dict] = []

            def collides(candidate: dict) -> bool:
                return any(
                    candidate["t0"] < kept["t1"] - 1e-3 and candidate["t1"] > kept["t0"] + 1e-3
                    for kept in clean
                )

            for opening in sorted([item for item in openings if item.get("door")], key=lambda item: item["t0"]):
                if collides(opening):
                    self.warnings.append(
                        f"two doors compete for the same span on the {side} elevation of {storey.id}; kept one"
                    )
                    continue
                clean.append(opening)
            for opening in sorted([item for item in openings if not item.get("door")], key=lambda item: item["t0"]):
                if collides(opening):
                    continue
                clean.append(opening)
            result[side] = clean

            # Record finalized openings on each room's wall map for furniture placement
            for item in clean:
                for space in storey.spaces:
                    if not self._touches(space, side):
                        continue
                    s0, s1 = self._span_along(space, side)
                    ov0 = max(s0, item["t0"])
                    ov1 = min(s1, item["t1"])
                    if ov1 - ov0 > 0.15:
                        self._record_space_opening(space, side, ov0, ov1, is_door=bool(item.get("door")))

        return result

    def build_exterior_walls(self, storey: Storey) -> None:
        sides = self._side_geometry()
        openings = self._openings_cache.get(storey.id) or self.exterior_openings(storey)
        thickness = self.b.defaults["exteriorWall"]
        base = storey.base
        for side, (start, end, _axis) in sides.items():
            self.wall_run(
                f"{side}_wall",
                start,
                end,
                thickness,
                base,
                storey.clear,
                openings[side],
                "wall",
                storey.id,
            )

    # ------------------------------------------------------------ interior
    def _select_private_doors(self, storey: Storey) -> set[frozenset[str]]:
        """Choose at most one automatic door for each private room on ``storey``.

        Without this pass, a bedroom or bathroom touching two circulation spaces
        (for example both the entry and the hall, or both a landing and a lounge)
        would receive two separate doors.
        """
        selected: set[frozenset[str]] = set()
        spaces = storey.spaces

        for space in spaces:
            if space.type not in PRIVATE_TYPES:
                continue
            # If the spec explicitly names a door for this room, honour the spec
            if any(space.id in door.between for door in self.b.doors):
                for door in self.b.doors:
                    if space.id in door.between:
                        selected.add(frozenset(door.between))
                continue

            best_pair: frozenset[str] | None = None
            best_score = -1.0
            for other in spaces:
                if other.id == space.id:
                    continue
                if (space.type, other.type) in NO_DOOR_PAIRS or (other.type, space.type) in NO_DOOR_PAIRS:
                    continue
                shared = self._shared_edge(space, other)
                if shared is None:
                    continue
                _kind, _line, start, end = shared
                span = end - start
                if span < 0.70:
                    continue
                if other.type in ("hall", "landing"):
                    priority = 400.0
                elif other.type == "entry":
                    priority = 300.0
                elif other.type in ("living", "lounge"):
                    priority = 200.0
                elif other.type == "dining":
                    priority = 100.0
                else:
                    continue
                score = priority + span
                if score > best_score:
                    best_score = score
                    best_pair = frozenset({space.id, other.id})
            if best_pair is not None:
                selected.add(best_pair)
        return selected

    def _stair_entry_neighbor(self, stair_space: Space, storey: Storey) -> str | None:
        """Identify the single circulation room that should open onto ``stair_space``."""
        for door in self.b.doors:
            if stair_space.id in door.between:
                other_id = door.between[0] if door.between[1] == stair_space.id else door.between[1]
                return other_id

        best_id: str | None = None
        best_score = -1.0
        for other in storey.spaces:
            if other.id == stair_space.id or other.type in PRIVATE_TYPES or other.type == "kitchen":
                continue
            shared = self._shared_edge(stair_space, other)
            if shared is None:
                continue
            kind, line, start, end = shared
            span = end - start
            if span < 0.75:
                continue
            # Prefer the front/entry side of the stairwell (y = stair_space.y0)
            at_foot = 200.0 if (kind == "h" and abs(line - stair_space.y0) < 0.05) else 0.0
            role = 120.0 if other.type in ("hall", "landing", "entry") else 60.0
            score = at_foot + role + span
            if score > best_score:
                best_score = score
                best_id = other.id
        return best_id

    def build_interior_walls(self, storey: Storey) -> None:
        thickness = self.b.defaults["interiorWall"]
        door_default = self.b.defaults["doorWidth"]
        door_height = self.b.defaults["doorHeight"]
        spaces = storey.spaces
        allowed_private_doors = self._select_private_doors(storey)
        stair_neighbors = {
            space.id: self._stair_entry_neighbor(space, storey)
            for space in spaces
            if space.type == "stair"
        }

        for i, first in enumerate(spaces):
            for second in spaces[i + 1 :]:
                shared = self._shared_edge(first, second)
                if shared is None:
                    continue
                kind, line, start, end = shared
                span = end - start
                if span < 0.35:
                    continue

                a = (start, line) if kind == "h" else (line, start)
                b = (end, line) if kind == "h" else (line, end)
                pair = frozenset({first.id, second.id})
                door = self._door_for(first.id, second.id)

                def solid_wall() -> None:
                    self.wall_run(
                        f"party_{first.id}_{second.id}",
                        a,
                        b,
                        thickness,
                        storey.base,
                        storey.clear,
                        [],
                        "wall_inner",
                        storey.id,
                    )

                # 1. Stairwell boundary: only open on the stair's entry edge to its hall/landing
                if first.type == "stair" or second.type == "stair":
                    stair_space = first if first.type == "stair" else second
                    other_space = second if first.type == "stair" else first
                    if stair_neighbors.get(stair_space.id) != other_space.id:
                        solid_wall()
                        continue
                    # Open framed portal into the stairwell (no swinging door leaf blocking steps)
                    width = min(max(1.15, span * 0.72), max(0.75, span - 0.24))
                    height = min(storey.clear - 0.25, max(door_height, 2.25))
                    centre = (start + end) / 2.0
                    t0 = centre - width / 2.0 - start
                    t1 = t0 + width
                    self.wall_run(
                        f"party_{first.id}_{second.id}",
                        a,
                        b,
                        thickness,
                        storey.base,
                        storey.clear,
                        [{"t0": t0, "t1": t1, "sill": 0.0, "head": height, "frame": True}],
                        "wall_inner",
                        storey.id,
                    )
                    self._record_interior_door(first, second, kind, line, start + t0, start + t1)
                    continue

                # 2. Private rooms: each private room only gets its single selected door
                if first.type in PRIVATE_TYPES or second.type in PRIVATE_TYPES:
                    if pair not in allowed_private_doors:
                        solid_wall()
                        continue

                # 3. Prohibited pairs without explicit override
                if door is None and (
                    (first.type, second.type) in NO_DOOR_PAIRS
                    or (second.type, first.type) in NO_DOOR_PAIRS
                ):
                    solid_wall()
                    continue

                # 4. Kitchen touching a hall/entry when it already opens to dining: keep solid
                if door is None and {first.type, second.type} in ({"kitchen", "hall"}, {"kitchen", "landing"}, {"kitchen", "entry"}):
                    has_dining = any(s.type == "dining" for s in spaces)
                    if has_dining:
                        solid_wall()
                        continue

                both_open_day = (
                    first.type in OPEN_DAY_TYPES and second.type in OPEN_DAY_TYPES
                )

                width = min(door.width if door else door_default, max(0.5, span - 0.26))
                if both_open_day:
                    # Open daytime flow (Entry -> Living -> Dining -> Kitchen, Entry -> Hall)
                    width = min(max(1.55, width), max(0.65, span - 0.30))
                height = door.height if door else door_height

                # Position the door: centered for open passages, corner-tucked for private rooms
                if door and abs(door.offset) > 1e-4:
                    centre = min(
                        max((start + end) / 2.0 + door.offset, start + width / 2.0 + 0.12),
                        end - width / 2.0 - 0.12,
                    )
                    hinge_at_t0 = True
                elif both_open_day:
                    centre = (start + end) / 2.0
                    hinge_at_t0 = True
                else:
                    # Tuck the door 0.24 m from the start corner so the leaf swings
                    # cleanly against the perpendicular wall and leaves the rest of the
                    # wall unbroken for beds, wardrobes, or desks.
                    lo = start + width / 2.0 + 0.12
                    hi = end - width / 2.0 - 0.12
                    preferred = min(max(start + 0.24 + width / 2.0, lo), hi)
                    centre = preferred
                    hinge_at_t0 = True

                t0 = centre - width / 2.0 - start
                t1 = t0 + width

                self.wall_run(
                    f"party_{first.id}_{second.id}",
                    a,
                    b,
                    thickness,
                    storey.base,
                    storey.clear,
                    [{"t0": t0, "t1": t1, "sill": 0.0, "head": height, "frame": True}],
                    "wall_inner",
                    storey.id,
                )

                self._record_interior_door(first, second, kind, line, start + t0, start + t1)

                if both_open_day:
                    continue

                # Hinged door leaf swinging into the private room (or larger room)
                target_room = (
                    first
                    if first.type in PRIVATE_TYPES and second.type not in PRIVATE_TYPES
                    else second
                    if second.type in PRIVATE_TYPES and first.type not in PRIVATE_TYPES
                    else (first if first.area >= second.area else second)
                )
                if kind == "h":
                    hinge = (start + t0 if hinge_at_t0 else start + t1, line)
                    along = (1.0 if hinge_at_t0 else -1.0, 0.0)
                    swing = (0.0, -1.0) if target_room.center[1] < line else (0.0, 1.0)
                else:
                    hinge = (line, start + t0 if hinge_at_t0 else start + t1)
                    along = (0.0, 1.0 if hinge_at_t0 else -1.0)
                    swing = (-1.0, 0.0) if target_room.center[0] < line else (1.0, 0.0)

                self.door_leaf(
                    f"door_{first.id}_{second.id}",
                    storey,
                    hinge,
                    along,
                    swing,
                    max(0.4, width - 0.05),
                    height,
                    storey.id,
                )

    def _record_interior_door(
        self,
        first: Space,
        second: Space,
        kind: str,
        line: float,
        c0: float,
        c1: float,
    ) -> None:
        """Record a doorway on both spaces' wall maps and reserve its approach zone.

        A door needs standing room in front of it. A wide open passage does not:
        a four-metre opening cannot be blocked by a table, and reserving a metre
        of floor across it would empty the room. The zone depth therefore scales
        with the opening width.
        """
        width = c1 - c0
        clear = 1.00 if width <= 1.30 else 0.45
        if kind == "h":
            for space in (first, second):
                if space.y1 <= line + 1e-4:
                    self.space_doors_by_side.setdefault(space.id, {}).setdefault("back", []).append((c0, c1))
                    self.door_clearance.setdefault(space.id, []).append((c0, max(space.y0, line - clear), c1, line))
                else:
                    self.space_doors_by_side.setdefault(space.id, {}).setdefault("front", []).append((c0, c1))
                    self.door_clearance.setdefault(space.id, []).append((c0, line, c1, min(space.y1, line + clear)))
        else:
            for space in (first, second):
                if space.x1 <= line + 1e-4:
                    self.space_doors_by_side.setdefault(space.id, {}).setdefault("right", []).append((c0, c1))
                    self.door_clearance.setdefault(space.id, []).append((max(space.x0, line - clear), c0, line, c1))
                else:
                    self.space_doors_by_side.setdefault(space.id, {}).setdefault("left", []).append((c0, c1))
                    self.door_clearance.setdefault(space.id, []).append((line, c0, min(space.x1, line + clear), c1))

    def _shared_edge(self, first: Space, second: Space):
        """Return ("h"|"v", line, start, end) for the boundary two rooms share."""
        if abs(first.y1 - second.y0) < 0.01:
            overlap = _overlap(first.x0, first.x1, second.x0, second.x1)
            if overlap > 0.01:
                return ("h", first.y1, max(first.x0, second.x0), min(first.x1, second.x1))
        if abs(second.y1 - first.y0) < 0.01:
            overlap = _overlap(first.x0, first.x1, second.x0, second.x1)
            if overlap > 0.01:
                return ("h", second.y1, max(first.x0, second.x0), min(first.x1, second.x1))
        if abs(first.x1 - second.x0) < 0.01:
            overlap = _overlap(first.y0, first.y1, second.y0, second.y1)
            if overlap > 0.01:
                return ("v", first.x1, max(first.y0, second.y0), min(first.y1, second.y1))
        if abs(second.x1 - first.x0) < 0.01:
            overlap = _overlap(first.y0, first.y1, second.y0, second.y1)
            if overlap > 0.01:
                return ("v", second.x1, max(first.y0, second.y0), min(first.y1, second.y1))
        return None

    def _door_for(self, a: str, b: str):
        for door in self.b.doors:
            if set(door.between) == {a, b}:
                return door
        return None

    # --------------------------------------------------------------- stairs
    def build_stairs(self) -> None:
        for stair in self.b.stairs:
            self._build_stair(stair)

    def _build_straight_stair(self, stair: Stair, storey: Storey) -> None:
        """One straight flight from the front of the stair rectangle to the back."""
        rise_total = storey.height
        flight = stair_flight(stair, storey)
        width = flight["width"]
        if flight["depth"] < 1.0 or width < 0.7:
            self.warnings.append(f'stair "{stair.id}" is too small to build and was skipped')
            return
        steps_count = flight["count"]
        tread = flight["tread"]
        rise = flight["riser"]
        if tread < 0.2:
            self.warnings.append(
                f'stair "{stair.id}" has {tread * 100:.0f} cm treads; it will walk badly'
            )
        centre_x = (stair.x0 + stair.x1) / 2.0
        steps = []
        for index in range(steps_count):
            y0 = stair.y0 + index * tread
            y1 = y0 + tread
            top = storey.base + rise * (index + 1)
            self.block(
                self.name("stair_step", storey.id),
                (centre_x, (y0 + y1) / 2.0, top - rise / 2.0),
                (width, tread, rise),
                "slab",
                storey.id,
                support="stair",
            )
            self.block(
                self.name("stair_nosing", storey.id),
                (centre_x, y0 + 0.035, top - 0.012),
                (width - 0.02, 0.07, 0.024),
                "nosing",
                storey.id,
            )
            steps.append({"flight": "a", "rect": [stair.x0, y0, stair.x1, y1], "top": top})

        self.stairs_manifest.append(
            {
                "id": stair.id,
                "storey": storey.id,
                "steps": steps,
                "landing": None,
                "top": storey.base + rise_total,
            }
        )

    def _build_stair(self, stair: Stair) -> None:
        storey = self.b.storey(stair.storey)
        if storey is None:
            return
        if stair.form == "straight":
            self._build_straight_stair(stair, storey)
            return
        rise_total = storey.height
        depth_total = stair.y1 - stair.y0
        if depth_total < 1.2:
            self.warnings.append(f'stair "{stair.id}" has almost no depth and was skipped')
            return

        flight = stair_flight(stair, storey)
        width = flight["width"]
        n = flight["count"]
        landing_depth = flight["landing"]
        run = flight["depth"] - landing_depth
        tread = flight["tread"]
        rise = flight["riser"]
        if tread < 0.2:
            self.warnings.append(
                f'stair "{stair.id}" has {tread * 100:.0f} cm treads; it will walk badly'
            )

        flight_a_x0 = stair.x0 + 0.05
        flight_a_x1 = flight_a_x0 + width
        flight_b_x1 = stair.x1 - 0.05
        flight_b_x0 = flight_b_x1 - width
        base = storey.base
        half = rise_total / 2.0

        steps_manifest = []
        for index in range(n):
            y0 = stair.y0 + index * tread
            y1 = y0 + tread
            top = base + rise * (index + 1)
            self.block(
                self.name("stair_a", storey.id),
                ((flight_a_x0 + flight_a_x1) / 2.0, (y0 + y1) / 2.0, top - rise / 2.0),
                (flight_a_x1 - flight_a_x0, tread, rise),
                "slab",
                storey.id,
                support="stair",
            )
            self.block(
                self.name("stair_nosing", storey.id),
                ((flight_a_x0 + flight_a_x1) / 2.0, y0 + 0.035, top - 0.012),
                (flight_a_x1 - flight_a_x0 - 0.02, 0.07, 0.024),
                "nosing",
                storey.id,
            )
            steps_manifest.append(
                {"flight": "a", "rect": [flight_a_x0, y0, flight_a_x1, y1], "top": top}
            )

        landing_y0 = stair.y0 + run
        landing_y1 = stair.y1
        landing_top = base + half
        self.block(
            self.name("stair_landing", storey.id),
            ((stair.x0 + stair.x1) / 2.0, (landing_y0 + landing_y1) / 2.0, landing_top - 0.11),
            (stair.x1 - stair.x0 - 0.1, landing_y1 - landing_y0, 0.22),
            "slab",
            storey.id,
            support="stair",
        )

        for index in range(n):
            y1 = landing_y0 - index * tread
            y0 = y1 - tread
            if y0 < stair.y0 - 1e-6:
                break
            top = base + half + rise * (index + 1)
            self.block(
                self.name("stair_b", storey.id),
                ((flight_b_x0 + flight_b_x1) / 2.0, (y0 + y1) / 2.0, top - rise / 2.0),
                (flight_b_x1 - flight_b_x0, tread, rise),
                "slab",
                storey.id,
                support="stair",
            )
            self.block(
                self.name("stair_nosing_b", storey.id),
                ((flight_b_x0 + flight_b_x1) / 2.0, y0 + 0.035, top - 0.012),
                (flight_b_x1 - flight_b_x0 - 0.02, 0.07, 0.024),
                "nosing",
                storey.id,
            )
            steps_manifest.append(
                {"flight": "b", "rect": [flight_b_x0, y0, flight_b_x1, y1], "top": top}
            )

        # A solid spine wall fills the well between the two flights. A thin plate
        # here leaves a slot wide enough to fall through, and a stair you can fall
        # off sideways is worse than no stair at all.
        gap_x0, gap_x1 = flight_a_x1, flight_b_x0
        if gap_x1 - gap_x0 > 0.12:
            self.block(
                self.name("stair_spine", storey.id),
                ((gap_x0 + gap_x1) / 2.0, stair.y0 + run / 2.0, base + half / 2.0),
                (gap_x1 - gap_x0, run, half),
                "wall_inner",
                storey.id,
                collider="wall",
            )
            self.block(
                self.name("stair_handrail", storey.id),
                ((gap_x0 + gap_x1) / 2.0, stair.y0 + run / 2.0, base + half + 0.02),
                (gap_x1 - gap_x0 + 0.06, run + 0.04, 0.04),
                "walnut",
                storey.id,
            )

        # Warn when the flights do not meet the stairwell walls: the leftover
        # strip beside a stair is a hole to fall down.
        space = next((item for item in storey.spaces if item.id == stair.space), None) if hasattr(stair, "space") else None
        for item in storey.spaces:
            if item.type == "stair" and item.x0 <= stair.x0 and item.x1 >= stair.x1 and item.y0 <= stair.y0 and item.y1 >= stair.y1:
                space = item
                break
        if space is not None:
            side_gap = max(stair.x0 - space.x0, space.x1 - stair.x1)
            if side_gap > 0.28:
                self.warnings.append(
                    f'stair "{stair.id}" leaves {side_gap * 100:.0f} cm beside the flights; '
                    "widen the stair rectangle to the stairwell walls so nobody can fall down the well"
                )

        self.stairs_manifest.append(
            {
                "id": stair.id,
                "storey": storey.id,
                "steps": steps_manifest,
                "landing": {"rect": [stair.x0, landing_y0, stair.x1, landing_y1], "top": landing_top},
                "top": base + rise_total,
            }
        )

    # ------------------------------------------------------------------ doors
    def door_leaf(
        self,
        name: str,
        storey: Storey,
        hinge: tuple[float, float],
        along: tuple[float, float],
        swing: tuple[float, float],
        width: float,
        height: float,
        storey_id: str,
    ) -> None:
        """A hinged door leaf with lever handles, authored around its hinge."""
        if width < 0.4 or height < 1.0:
            return
        closed_yaw = math.atan2(along[1], along[0])
        open_yaw = math.atan2(swing[1], swing[0])
        mesh = box_xyz((width / 2.0, height / 2.0, 0.0), (width, height, 0.045))
        # Add subtle lever handle geometry on both faces of the door leaf
        handle_x = max(0.25, width - 0.10)
        handle_y = min(1.00, height * 0.48)
        mesh.merge(box_xyz((handle_x, handle_y, 0.0), (0.03, 0.03, 0.11)))
        mesh.merge(box_xyz((handle_x - 0.05, handle_y, 0.052), (0.11, 0.022, 0.018)))
        mesh.merge(box_xyz((handle_x - 0.05, handle_y, -0.052), (0.11, 0.022, 0.018)))
        self.glb.add_mesh(
            self.name(name, storey_id),
            mesh.positions,
            mesh.normals,
            mesh.indices,
            self.mat("walnut"),
            extras={
                "storey": storey_id,
                "door": True,
                "closed": round(closed_yaw, 5),
                "open": round(open_yaw, 5),
            },
            translation=(hinge[0], storey.base, -hinge[1]),
            rotation_y=closed_yaw,
        )

    # ------------------------------------------------------------- balconies
    def build_balcony(self, balcony, storey: Storey) -> None:
        x0, y0, x1, y1 = balcony_rect(balcony, self.b)
        thickness = 0.22
        self.block(
            self.name("balcony_slab", storey.id),
            ((x0 + x1) / 2.0, (y0 + y1) / 2.0, storey.base - thickness / 2.0),
            (x1 - x0, y1 - y0, thickness),
            "slab",
            storey.id,
            support="balcony",
        )
        self.block(
            self.name("balcony_soffit_band", storey.id),
            ((x0 + x1) / 2.0, (y0 + y1) / 2.0, storey.base - thickness - 0.02),
            (x1 - x0 + 0.04, y1 - y0 + 0.04, 0.06),
            "stone",
            storey.id,
        )

        rail = balcony.railing
        edges = [
            ("h", y0, x0, x1, "outer"),
            ("h", y1, x0, x1, "wall_side"),
            ("v", x0, y0, y1, "left"),
            ("v", x1, y0, y1, "right"),
        ]
        skip = {"front": "wall_side", "back": "wall_side", "left": "right", "right": "left"}
        for kind, fixed, start, end, label in edges:
            if label == skip[balcony.side]:
                continue
            length = end - start
            if length < 0.2:
                continue
            centre = (start + end) / 2.0
            if kind == "h":
                position = (centre, fixed)
                glass_size = (length, 0.028, rail)
                cap_size = (length + 0.04, 0.07, 0.05)
            else:
                position = (fixed, centre)
                glass_size = (0.028, length, rail)
                cap_size = (0.07, length + 0.04, 0.05)
            self.block(
                self.name("balustrade_glass", storey.id),
                (position[0], position[1], storey.base + rail / 2.0),
                glass_size,
                "glass_clear",
                storey.id,
                collider="rail",
            )
            self.block(
                self.name("balustrade_cap", storey.id),
                (position[0], position[1], storey.base + rail + 0.025),
                cap_size,
                "metal",
                storey.id,
                collider="rail",
            )

        self.balconies_manifest.append(
            {
                "id": balcony.id,
                "storey": storey.id,
                "side": balcony.side,
                "rect": [x0, y0, x1, y1],
                "area": (x1 - x0) * (y1 - y0),
                "railing": rail,
            }
        )

    # ------------------------------------------------------------------ roof
    def build_roof(self) -> None:
        last = self.b.storeys[-1]
        thickness = self.b.defaults["slab"]
        roof = self.b.roof
        kind = roof.get("type", "terrace")

        # If a stair climbs from the top storey to a walkable terrace roof,
        # cut the stair opening in the roof slab and guard it with a balustrade.
        hole = None
        if kind in ("terrace", "flat"):
            for stair in self.b.stairs:
                if stair.storey == last.id:
                    hole = (stair.x0, stair.y0, stair.x1, stair.y1)
                    break

        self.slab(last.id, thickness, last.top, hole, "roof", "roof")
        self.build_edge_band(last, "slab", level=last.top)

        if hole is not None:
            hx0, hy0, hx1, hy1 = hole
            rail = 1.05
            # Guard the 3 non-exit sides of the roof stairwell opening
            guards = [
                ((hx0 + hx1) / 2.0, hy1, (hx1 - hx0, 0.04, rail), (hx1 - hx0 + 0.06, 0.08, 0.05)),
                (hx0, (hy0 + hy1) / 2.0, (0.04, hy1 - hy0, rail), (0.08, hy1 - hy0 + 0.06, 0.05)),
                (hx1, (hy0 + hy1) / 2.0, (0.04, hy1 - hy0, rail), (0.08, hy1 - hy0 + 0.06, 0.05)),
            ]
            for gx, gy, gsize, csize in guards:
                self.block(
                    self.name("roof_stair_glass", last.id),
                    (gx, gy, last.top + rail / 2.0),
                    gsize,
                    "glass_clear",
                    last.id,
                    collider="rail",
                )
                self.block(
                    self.name("roof_stair_cap", last.id),
                    (gx, gy, last.top + rail + 0.025),
                    csize,
                    "metal",
                    last.id,
                    collider="rail",
                )

        if kind in ("shed", "gable"):
            self._build_pitched_roof(last, kind)
            return

        parapet = roof.get("parapet", 0.9)
        if parapet <= 0:
            return
        wall_thickness = self.b.defaults["exteriorWall"] * 0.7
        base = last.top
        for side, (start, end, _axis) in self._side_geometry().items():
            self.wall_run(
                f"parapet_{side}",
                start,
                end,
                wall_thickness,
                base,
                parapet,
                [],
                "wall",
                last.id,
            )

    # ------------------------------------------------------------ slab edge
    def build_edge_band(self, storey: Storey, material: str = "slab", level: float | None = None) -> None:
        """A slightly proud slab edge at each floor: flush with the floor top, never protruding inside."""
        ext = self.b.defaults["exteriorWall"]
        band_depth = 0.08
        height = 0.20
        top = level if level is not None else storey.base
        z = top - height / 2.0
        outset = ext / 2.0 + band_depth / 2.0 - 0.01
        w = self.b.width
        d = self.b.depth
        bands = [
            ((w / 2.0, -outset), (w + outset * 2.0, band_depth, height)),
            ((w / 2.0, d + outset), (w + outset * 2.0, band_depth, height)),
            ((-outset, d / 2.0), (band_depth, d, height)),
            ((w + outset, d / 2.0), (band_depth, d, height)),
        ]
        for (cx, cy), size in bands:
            self.block(self.name("edge_band", storey.id), (cx, cy, z), size, material, storey.id)

    def _build_pitched_roof(self, last: Storey, kind: str) -> None:
        """Shed or gable roof sitting on the top slab, with an overhang at the eaves."""
        roof = self.b.roof
        overhang = max(0.0, roof.get("overhang", 0.6))
        pitch = math.radians(max(3.0, min(70.0, roof.get("pitch", 22.0))))
        x0, y0 = -overhang, -overhang
        x1, y1 = self.b.width + overhang, self.b.depth + overhang
        z_eave = last.top
        fascia = 0.18

        if kind == "shed":
            rise = (y1 - y0) * math.tan(pitch)
            self.emit(
                self.name("roof_shed", last.id),
                wedge(x0, x1, y0, y1, z_eave - fascia, z_eave, z_eave + rise, "y0"),
                "roof",
                last.id,
            )
            self.block(
                self.name("roof_fascia", last.id),
                ((x0 + x1) / 2.0, y1, z_eave - fascia / 2.0),
                (x1 - x0, 0.06, fascia),
                "frame",
                last.id,
            )
            return

        ridge = roof.get("ridge", "x")
        if ridge == "y":
            xm = (x0 + x1) / 2.0
            rise = (xm - x0) * math.tan(pitch)
            halves = (
                wedge(x0, xm, y0, y1, z_eave - fascia, z_eave, z_eave + rise, "x1"),
                wedge(xm, x1, y0, y1, z_eave - fascia, z_eave, z_eave + rise, "x0"),
            )
        else:
            ym = (y0 + y1) / 2.0
            rise = (ym - y0) * math.tan(pitch)
            halves = (
                wedge(x0, x1, y0, ym, z_eave - fascia, z_eave, z_eave + rise, "y1"),
                wedge(x0, x1, ym, y1, z_eave - fascia, z_eave, z_eave + rise, "y0"),
            )
        for index, half in enumerate(halves):
            self.emit(self.name(f"roof_gable_{index}", last.id), half, "roof", last.id)

        # Eaves fascia on the two long sides
        for y_edge in (y0, y1):
            self.block(
                self.name("roof_fascia", last.id),
                ((x0 + x1) / 2.0, y_edge, z_eave - fascia / 2.0),
                (x1 - x0, 0.06, fascia),
                "frame",
                last.id,
            )

    # ---------------------------------------------------------- floor finish
    def build_floor_finish(self, storey: Storey) -> None:
        finish_by_type = {
            "bath": "ceramic",
            "wc": "ceramic",
            "kitchen": "ceramic",
            "terrace": "paving",
            "balcony": "paving",
            "garage": "paving",
            "entry": "paving",
        }
        # Avoid pouring ceiling finish over the stair opening from the floor above
        stair_hole = None
        for stair in self.b.stairs:
            if stair.storey == storey.id:
                stair_hole = (stair.x0, stair.y0, stair.x1, stair.y1)
                break

        for space in storey.spaces:
            material = finish_by_type.get(space.type, "oak_light")
            if space.type != "stair" or storey.index == 0:
                self.block(
                    self.name("floor_finish", storey.id),
                    (space.center[0], space.center[1], storey.base + 0.008),
                    (space.width - 0.02, space.depth - 0.02, 0.016),
                    material,
                    storey.id,
                )
            if space.type not in ("terrace", "balcony", "garage", "stair"):
                if stair_hole and _rects_overlap((space.x0, space.y0, space.x1, space.y1), stair_hole):
                    continue
                self.block(
                    self.name("ceiling_finish", storey.id),
                    (space.center[0], space.center[1], storey.base + storey.clear + 0.01),
                    (space.width - 0.02, space.depth - 0.02, 0.02),
                    "wall_inner",
                    storey.id,
                )

    # -------------------------------------------------------------- furniture
    def build_furniture(self, storey: Storey) -> None:
        """Place furniture after all doors and windows on the storey are known."""
        for space in storey.spaces:
            pieces = furnish(
                space,
                storey.base + 0.02,
                storey.clear,
                glazed_sides=self.space_windows.get(space.id, set()),
                doors_by_side=self.space_doors_by_side.get(space.id, {}),
                windows_by_side=self.space_windows_by_side.get(space.id, {}),
                door_zones=self.door_clearance.get(space.id, []),
            )
            for piece in pieces:
                self.emit(
                    self.name(piece.material, storey.id),
                    piece.mesh,
                    piece.material,
                    storey.id,
                    collider="furniture" if piece.blocks else None,
                    extras={"space": space.id, "furniture": True},
                )
                if piece.blocks:
                    self.furniture_zones.setdefault(space.id, []).append(self._plan_bounds(piece.mesh))

    @staticmethod
    def _plan_bounds(mesh: MeshData) -> tuple[float, float, float, float]:
        xs = [point[0] for point in mesh.positions]
        zs = [point[2] for point in mesh.positions]
        return (min(xs), -max(zs), max(xs), -min(zs))

    # ----------------------------------------------------------------- lights
    def build_lights(self, storey: Storey) -> None:
        for space in storey.spaces:
            if space.type in ("store", "garage"):
                continue
            if space.type == "stair":
                # A stairwell is the one place a house is genuinely dark: no
                # window reaches it and the flights shade whatever is below them.
                # Light it at the landing, where you actually look.
                half = storey.height / 2.0
                centre = space.center
                self.luminaires.append(
                    {
                        "position": [centre[0], storey.base + half + 0.7, -centre[1]],
                        "intensity": 7.0 + space.area * 0.35,
                        "distance": 5.0 + space.area * 0.12,
                        "space": space.id,
                        "storey": storey.id,
                    }
                )
                self.block(
                    self.name("ceiling_light", storey.id),
                    (centre[0], centre[1], storey.base + storey.clear - 0.75),
                    (0.26, 0.26, 0.05),
                    "led",
                    storey.id,
                )
                continue
            centre = space.center
            z = storey.base + storey.clear - 0.02
            self.block(
                self.name("ceiling_light", storey.id),
                (centre[0], centre[1], z),
                (0.34, 0.34, 0.05),
                "led",
                storey.id,
            )
            self.luminaires.append(
                {
                    "position": [centre[0], storey.base + storey.clear - 0.32, -centre[1]],
                    "intensity": 9.0 + space.area * 0.55,
                    "distance": 6.0 + space.area * 0.15,
                    "space": space.id,
                    "storey": storey.id,
                }
            )

    # ------------------------------------------------------------------ main
    def build(self) -> BuildReport:
        self.build_site()
        defaults = self.b.defaults
        slab = defaults["slab"]
        plinth = max(0.45, slab * 0.8)

        for storey in self.b.storeys:
            hole = None
            if storey.index > 0:
                below = self.b.storeys[storey.index - 1]
                for stair in self.b.stairs:
                    if stair.storey == below.id:
                        hole = (stair.x0, stair.y0, stair.x1, stair.y1)
                        break
            if storey.index == 0:
                self.slab(storey.id, plinth, storey.base, None, "plinth", "floor")
            else:
                self.slab(storey.id, slab, storey.base, hole, "slab", "floor")
            self.build_edge_band(storey, "stone" if storey.index == 0 else "slab")
            self.build_floor_finish(storey)

            # 1. Decide exterior openings (windows, entrance, balcony doors)
            self._openings_cache[storey.id] = self.exterior_openings(storey)
            self.build_exterior_walls(storey)
            for balcony in self.b.balconies:
                if balcony.storey == storey.id:
                    self.build_balcony(balcony, storey)

            # 2. Decide interior walls, doorways, and door swing zones
            self.build_interior_walls(storey)

            # 3. Furnish every room with complete knowledge of doors and windows
            self.build_furniture(storey)
            self.build_lights(storey)

            self.spaces_manifest.extend(
                {
                    "id": space.id,
                    "name": space.name,
                    "type": space.type,
                    "storey": storey.id,
                    "rect": [space.x0, space.y0, space.x1, space.y1],
                    "area": space.area,
                    "center": [space.center[0], storey.base, -space.center[1]],
                }
                for space in storey.spaces
            )

        self.build_stairs()
        self.build_roof()

        spawn = self._spawn()
        report = BuildReport()
        report.spaces = self.spaces_manifest
        report.warnings = self.warnings
        report.storeys = [
            {
                "id": storey.id,
                "index": storey.index,
                "base": storey.base,
                "top": storey.top,
                "height": storey.height,
                "spaces": len(storey.spaces),
                "area_net": sum(space.area for space in storey.spaces),
            }
            for storey in self.b.storeys
        ]
        report.manifest_data = {
            "version": "0.1",
            "name": self.b.name,
            "units": "m",
            "storeys": report.storeys,
            "spaces": self.spaces_manifest,
            "stairs": self.stairs_manifest,
            "balconies": self.balconies_manifest,
            "colliders": self.colliders,
            "supports": self.supports,
            "luminaires": self.luminaires,
            "spawn": spawn,
            "site": {**getattr(self, "site_bounds", {}), "surface": getattr(self, "site_color", "#8A7B62")},
            "bounds": {
                "min": [0.0, 0.0, -self.b.depth],
                "max": [self.b.width, self.b.top + self.b.roof.get("parapet", 0.0), 0.0],
            },
        }
        return report

    def _spawn(self) -> dict:
        """Start on the pavement outside the front door, facing into the house."""
        ground = self.b.storeys[0]
        entrance = self.b.entrance
        space = self.b.space(entrance["space"]) if entrance["space"] else None
        if space is not None and space.storey == ground.id:
            side = entrance["side"]
            if side in ("front", "back"):
                door_x = (space.x0 + space.x1) / 2.0 + entrance.get("offset", 0.0)
                outside = -2.4 if side == "front" else self.b.depth + 2.4
                return {
                    "position": [door_x, ground.base - 0.15 + EYE_HEIGHT, -outside],
                    "yaw": 0.0 if side == "front" else math.pi,
                    "space": space.id,
                }
            door_y = (space.y0 + space.y1) / 2.0 + entrance.get("offset", 0.0)
            outside = -2.4 if side == "left" else self.b.width + 2.4
            return {
                "position": [outside, ground.base - 0.15 + EYE_HEIGHT, -door_y],
                "yaw": -math.pi / 2.0 if side == "left" else math.pi / 2.0,
                "space": space.id,
            }

        candidates = [space for space in ground.spaces if space.type not in ("stair", "store", "garage")]
        space = max(candidates or ground.spaces, key=lambda item: item.area)
        centre_x, centre_y = space.center
        return {
            "position": [centre_x, ground.base + EYE_HEIGHT, -centre_y],
            "yaw": 0.0,
            "space": space.id,
        }

    # ---------------------------------------------------------------- output
    def export(self, out_dir: str | Path, stem: str) -> BuildReport:
        report = self.build()
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        glb_path = out_dir / f"{stem}.glb"
        manifest_path = out_dir / f"{stem}.manifest.json"

        manifest = report.manifest_data
        stats = self.glb.export(glb_path, scene_extras={"thau": manifest}, generator="thau3d")
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        report.nodes = stats["nodes"]
        report.triangles = stats["triangles"]
        report.bytes = stats["bytes"]
        report.materials = stats["materials"]
        report.glb = glb_path
        report.manifest = manifest_path
        return report


def build_file(spec_path: str | Path, out_dir: str | Path, stem: str | None = None) -> BuildReport:
    from .spec import load_spec

    building = load_spec(spec_path)
    chosen = stem or Path(spec_path).stem
    return Builder(building).export(out_dir, chosen)
