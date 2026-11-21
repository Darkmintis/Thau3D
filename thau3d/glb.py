"""A small, dependency-free glTF 2.0 binary (GLB) writer.

Thau3D ships its own exporter on purpose:

* no native dependencies, so ``pip install thau3d`` is instant and works anywhere
* full control over materials, node names and ``extras`` (the manifest rides along)
* byte-stable output: the same spec always produces the same file

The writer speaks glTF space (Y up, metres). Callers are expected to convert
from their own authoring space before handing vertices over.
"""

from __future__ import annotations

import json
import struct

FLOAT = 5126
UNSIGNED_INT = 5125
UNSIGNED_SHORT = 5123
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963


class GLB:
    """Accumulates meshes, materials and nodes, then writes a .glb file."""

    def __init__(self) -> None:
        self._buffer = bytearray()
        self._buffer_views: list[dict] = []
        self._accessors: list[dict] = []
        self._materials: list[dict] = []
        self._material_index: dict[str, int] = {}
        self._meshes: list[dict] = []
        self._nodes: list[dict] = []
        self.vertex_count = 0
        self.triangle_count = 0

    # ------------------------------------------------------------------ buffer
    def _align(self, boundary: int) -> None:
        while len(self._buffer) % boundary:
            self._buffer.append(0)

    def _add_view(self, data: bytes, target: int) -> int:
        self._align(4)
        offset = len(self._buffer)
        self._buffer += data
        self._buffer_views.append(
            {
                "buffer": 0,
                "byteOffset": offset,
                "byteLength": len(data),
                "target": target,
            }
        )
        return len(self._buffer_views) - 1

    def _add_accessor(
        self,
        view: int,
        component_type: int,
        count: int,
        kind: str,
        minimum: list[float] | None = None,
        maximum: list[float] | None = None,
    ) -> int:
        accessor: dict = {
            "bufferView": view,
            "componentType": component_type,
            "count": count,
            "type": kind,
        }
        if minimum is not None and maximum is not None:
            accessor["min"] = [round(v, 6) for v in minimum]
            accessor["max"] = [round(v, 6) for v in maximum]
        self._accessors.append(accessor)
        return len(self._accessors) - 1

    # --------------------------------------------------------------- materials
    def material(
        self,
        key: str,
        *,
        color: str,
        metallic: float = 0.0,
        roughness: float = 0.8,
        opacity: float = 1.0,
        emissive: str | None = None,
        emissive_strength: float = 1.0,
        double_sided: bool = True,
    ) -> int:
        """Register (once) and return the index of a PBR material."""
        if key in self._material_index:
            return self._material_index[key]

        rgba = _hex_to_rgba(color, opacity)
        pbr: dict = {
            "baseColorFactor": [round(c, 5) for c in rgba],
            "metallicFactor": round(metallic, 4),
            "roughnessFactor": round(roughness, 4),
        }
        if emissive:
            pbr["emissiveFactor"] = [round(c * emissive_strength, 5) for c in _hex_to_rgb(emissive)]
        material: dict = {
            "name": key,
            "pbrMetallicRoughness": pbr,
            "doubleSided": double_sided,
        }
        if opacity < 1.0:
            material["alphaMode"] = "BLEND"
        self._materials.append(material)
        self._material_index[key] = len(self._materials) - 1
        return self._material_index[key]

    def has_material(self, key: str) -> bool:
        return key in self._material_index

    # ------------------------------------------------------------------ meshes
    def add_mesh(
        self,
        name: str,
        positions: list[tuple[float, float, float]],
        normals: list[tuple[float, float, float]],
        indices: list[int],
        material_index: int,
        *,
        extras: dict | None = None,
    ) -> int:
        if not positions or not indices:
            return -1

        flat_pos: list[float] = []
        for x, y, z in positions:
            flat_pos.extend((x, y, z))
        flat_norm: list[float] = []
        for x, y, z in normals:
            flat_norm.extend((x, y, z))
        _normalize_normals(flat_norm)

        bounds_min = [
            min(flat_pos[0::3]),
            min(flat_pos[1::3]),
            min(flat_pos[2::3]),
        ]
        bounds_max = [
            max(flat_pos[0::3]),
            max(flat_pos[1::3]),
            max(flat_pos[2::3]),
        ]

        position_view = self._add_view(
            struct.pack(f"<{len(flat_pos)}f", *flat_pos), ARRAY_BUFFER
        )
        normal_view = self._add_view(
            struct.pack(f"<{len(flat_norm)}f", *flat_norm), ARRAY_BUFFER
        )
        position_accessor = self._add_accessor(
            position_view, FLOAT, len(positions), "VEC3", bounds_min, bounds_max
        )
        normal_accessor = self._add_accessor(
            normal_view, FLOAT, len(positions), "VEC3"
        )

        if max(indices) < 65536:
            index_bytes = struct.pack(f"<{len(indices)}H", *indices)
            component_type = UNSIGNED_SHORT
        else:
            index_bytes = struct.pack(f"<{len(indices)}I", *indices)
            component_type = UNSIGNED_INT
        index_view = self._add_view(index_bytes, ELEMENT_ARRAY_BUFFER)
        index_accessor = self._add_accessor(
            index_view, component_type, len(indices), "SCALAR"
        )

        self._meshes.append(
            {
                "name": name,
                "primitives": [
                    {
                        "attributes": {
                            "POSITION": position_accessor,
                            "NORMAL": normal_accessor,
                        },
                        "indices": index_accessor,
                        "material": material_index,
                        "mode": 4,
                    }
                ],
            }
        )
        mesh_index = len(self._meshes) - 1
        node: dict = {"name": name, "mesh": mesh_index}
        if extras:
            node["extras"] = extras
        self._nodes.append(node)

        self.vertex_count += len(positions)
        self.triangle_count += len(indices) // 3
        return len(self._nodes) - 1

    # ------------------------------------------------------------------ export
    def export(self, path: str, *, scene_extras: dict | None = None, generator: str = "thau3d") -> dict:
        document: dict = {
            "asset": {"version": "2.0", "generator": generator},
            "scene": 0,
            "scenes": [{"name": "Thau3D", "nodes": list(range(len(self._nodes)))}],
            "nodes": self._nodes,
            "meshes": self._meshes,
            "materials": self._materials,
            "accessors": self._accessors,
            "bufferViews": self._buffer_views,
            "buffers": [{"byteLength": len(self._buffer)}],
        }
        if scene_extras:
            document["scenes"][0]["extras"] = scene_extras

        json_chunk = json.dumps(
            document, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
        while len(json_chunk) % 4:
            json_chunk += b" "

        bin_chunk = bytes(self._buffer)
        while len(bin_chunk) % 4:
            bin_chunk += b"\x00"

        total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
        with open(path, "wb") as handle:
            handle.write(struct.pack("<III", 0x46546C67, 2, total))
            handle.write(struct.pack("<II", len(json_chunk), 0x4E4F534A))
            handle.write(json_chunk)
            handle.write(struct.pack("<II", len(bin_chunk), 0x004E4942))
            handle.write(bin_chunk)

        return {
            "nodes": len(self._nodes),
            "meshes": len(self._meshes),
            "materials": len(self._materials),
            "vertices": self.vertex_count,
            "triangles": self.triangle_count,
            "bytes": total,
        }


# -------------------------------------------------------------------- helpers
def _hex_to_rgb(value: str) -> tuple[float, float, float]:
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError(f"material colour must be #rgb or #rrggbb, got {value!r}")
    return (
        int(text[0:2], 16) / 255.0,
        int(text[2:4], 16) / 255.0,
        int(text[4:6], 16) / 255.0,
    )


def _hex_to_rgba(value: str, opacity: float) -> tuple[float, float, float, float]:
    red, green, blue = _hex_to_rgb(value)
    return (red, green, blue, opacity)


def _normalize_normals(flat: list[float]) -> None:
    for i in range(0, len(flat), 3):
        x, y, z = flat[i], flat[i + 1], flat[i + 2]
        length = (x * x + y * y + z * z) ** 0.5
        if length > 1e-9:
            flat[i] = x / length
            flat[i + 1] = y / length
            flat[i + 2] = z / length
