"""Primitive geometry, authored in plan space and emitted in glTF space.

Plan space (what a floor drawing uses):
    x -> east / width
    y -> north / depth, away from the street
    z -> up

glTF space (Y up, -Z forward):
    (x, y, z)_plan  ->  (x, z, -y)_gl

The mapping is a pure rotation, so handedness and triangle winding are preserved
and normals transform with the same rule.
"""

from __future__ import annotations

import math

Vec3 = tuple[float, float, float]


def plan_to_gl(point: Vec3) -> Vec3:
    x, y, z = point
    return (x, z, -y)


def gl_to_plan(point: Vec3) -> Vec3:
    x, y, z = point
    return (x, -z, y)


def _subtract(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


class MeshData:
    """Positions/normals/indices in glTF space."""

    __slots__ = ("positions", "normals", "indices")

    def __init__(self) -> None:
        self.positions: list[Vec3] = []
        self.normals: list[Vec3] = []
        self.indices: list[int] = []

    def quad(self, a: Vec3, b: Vec3, c: Vec3, d: Vec3, normal: Vec3) -> None:
        """Add a quad, flipping the winding if needed so it faces ``normal``."""
        winding = _cross(_subtract(b, a), _subtract(c, a))
        if _dot(winding, normal) < 0:
            b, d = d, b
        start = len(self.positions)
        for corner in (a, b, c, d):
            self.positions.append(plan_to_gl(corner))
            self.normals.append(plan_to_gl(normal))
        self.indices.extend((start, start + 1, start + 2, start, start + 2, start + 3))

    def extend(self, other: "MeshData") -> None:
        offset = len(self.positions)
        self.positions.extend(other.positions)
        self.normals.extend(other.normals)
        self.indices.extend(i + offset for i in other.indices)


def box(center: Vec3, size: Vec3, yaw: float = 0.0) -> MeshData:
    """Axis-aligned (optionally yawed about plan Z) box."""
    cx, cy, cz = center
    sx, sy, sz = size
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0

    corners = {
        "---": (-hx, -hy, -hz),
        "+--": (hx, -hy, -hz),
        "++-": (hx, hy, -hz),
        "-+-": (-hx, hy, -hz),
        "--+": (-hx, -hy, hz),
        "+++": (hx, hy, hz),
        "-++": (-hx, hy, hz),
        "+-+": (hx, -hy, hz),
    }

    cos_yaw = math.cos(yaw)
    sin_yaw = math.sin(yaw)

    def place(local: Vec3) -> Vec3:
        lx, ly, lz = local
        rx = lx * cos_yaw - ly * sin_yaw
        ry = lx * sin_yaw + ly * cos_yaw
        return (cx + rx, cy + ry, cz + lz)

    mesh = MeshData()
    faces = (
        ("---", "-+-", "-++", "--+", (-1, 0, 0)),
        ("+--", "++-", "+++", "+-+", (1, 0, 0)),
        ("---", "--+", "+-+", "+--", (0, -1, 0)),
        ("-+-", "++-", "+++", "-++", (0, 1, 0)),
        ("---", "+--", "++-", "-+-", (0, 0, -1)),
        ("--+", "+-+", "+++", "-++", (0, 0, 1)),
    )
    for a, b, c, d, normal in faces:
        mesh.quad(
            place(corners[a]),
            place(corners[b]),
            place(corners[c]),
            place(corners[d]),
            normal,
        )
    return mesh


def cylinder(
    center: Vec3,
    radius: float,
    height: float,
    segments: int = 16,
) -> MeshData:
    """Vertical cylinder (plan Z axis) centred on ``center`` with ``height``."""
    cx, cy, cz = center
    bottom = cz - height / 2.0
    top = cz + height / 2.0
    mesh = MeshData()

    ring = []
    for index in range(segments):
        angle = 2.0 * math.pi * index / segments
        ring.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))

    for index in range(segments):
        x0, y0 = ring[index]
        x1, y1 = ring[(index + 1) % segments]
        mid_x = (x0 + x1) / 2.0 - cx
        mid_y = (y0 + y1) / 2.0 - cy
        length = math.hypot(mid_x, mid_y) or 1.0
        normal = (mid_x / length, mid_y / length, 0.0)
        mesh.quad(
            (x0, y0, bottom),
            (x1, y1, bottom),
            (x1, y1, top),
            (x0, y0, top),
            normal,
        )

    for z_value, normal in ((top, (0.0, 0.0, 1.0)), (bottom, (0.0, 0.0, -1.0))):
        start = len(mesh.positions)
        for x, y in ring:
            mesh.positions.append(plan_to_gl((x, y, z_value)))
            mesh.normals.append(plan_to_gl(normal))
        center_index = start + segments
        mesh.positions.append(plan_to_gl((cx, cy, z_value)))
        mesh.normals.append(plan_to_gl(normal))
        for index in range(segments):
            a = start + index
            b = start + (index + 1) % segments
            if normal[2] > 0:
                mesh.indices.extend((a, b, center_index))
            else:
                mesh.indices.extend((b, a, center_index))

    return mesh
