"""End to end: build the example, check the GLB contract, prove determinism."""

import hashlib
import json
import struct
import tempfile
import unittest
from pathlib import Path

from thau3d.build import Builder
from thau3d.spec import load_spec

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "housewalk" / "house.thau.json"


def read_gltf(path: Path) -> dict:
    data = path.read_bytes()
    magic, version, _length = struct.unpack("<III", data[:12])
    assert magic == 0x46546C67, "not a GLB"
    assert version == 2
    json_length, _kind = struct.unpack("<II", data[12:20])
    return json.loads(data[20 : 20 + json_length].decode("utf-8"))


class BuildTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        building = load_spec(EXAMPLE)
        cls.report = Builder(building).export(cls.tmp, "house")
        cls.gltf = read_gltf(cls.report.glb)
        cls.manifest = json.loads(cls.report.manifest.read_text(encoding="utf-8"))

    def test_outputs_exist(self):
        self.assertTrue(self.report.glb.exists())
        self.assertTrue(self.report.manifest.exists())
        self.assertGreater(self.report.nodes, 400)

    def test_every_primitive_has_a_material(self):
        # this is the failure that turned every cutaway into clay
        materials = self.gltf.get("materials", [])
        self.assertGreater(len(materials), 20)
        for mesh in self.gltf["meshes"]:
            for primitive in mesh["primitives"]:
                self.assertIn("material", primitive, f'{mesh["name"]} lost its material')
                self.assertLess(primitive["material"], len(materials))

    def test_glass_is_transparent(self):
        glass = [m for m in self.gltf["materials"] if m["name"] == "glass"]
        self.assertEqual(len(glass), 1)
        self.assertEqual(glass[0]["alphaMode"], "BLEND")
        self.assertLess(glass[0]["pbrMetallicRoughness"]["baseColorFactor"][3], 0.5)

    def test_nodes_carry_storey_tags(self):
        tagged = [node for node in self.gltf["nodes"] if (node.get("extras") or {}).get("storey")]
        self.assertGreater(len(tagged), 300)
        storeys = {node["extras"]["storey"] for node in tagged}
        self.assertEqual(storeys, {"ground", "first", "second"})

    def test_manifest_contract(self):
        for key in ("storeys", "spaces", "stairs", "colliders", "supports", "luminaires", "spawn", "bounds"):
            self.assertIn(key, self.manifest)
        self.assertEqual(len(self.manifest["storeys"]), 3)
        self.assertEqual(len(self.manifest["spaces"]), 18)
        self.assertGreater(len(self.manifest["colliders"]), 100)
        self.assertGreater(len(self.manifest["supports"]), 30)
        self.assertEqual(len(self.manifest["stairs"]), 3)

    def test_spawn_sits_inside_a_space(self):
        spawn = self.manifest["spawn"]
        space = next(item for item in self.manifest["spaces"] if item["id"] == spawn["space"])
        x, _y, z = spawn["position"]
        x0, y0, x1, y1 = space["rect"]
        self.assertTrue(x0 <= x <= x1, "spawn x outside its space")
        self.assertTrue(-y1 <= z <= -y0, "spawn z outside its space")

    def test_stairs_climb_a_full_storey(self):
        storeys = {storey["id"]: storey for storey in self.manifest["storeys"]}
        for stair in self.manifest["stairs"]:
            storey = storeys[stair["storey"]]
            expected = storey["base"] + storey["height"]
            self.assertAlmostEqual(stair["top"], expected, places=3)
            tops = sorted(step["top"] for step in stair["steps"])
            self.assertGreater(len(tops), 10)
            rises = [b - a for a, b in zip(tops, tops[1:]) if b > a]
            self.assertTrue(rises, "stair has no rising steps")
            self.assertLess(max(rises), 0.2, "a riser is taller than 20 cm")

    def test_supports_cover_every_storey(self):
        floors = [entry for entry in self.manifest["supports"] if entry["tag"] == "floor"]
        self.assertGreaterEqual(len(floors), 3)
        tops = {round(entry["max"][1], 3) for entry in floors}
        for storey in self.manifest["storeys"]:
            self.assertIn(round(storey["base"], 3), tops)


class DeterminismTest(unittest.TestCase):
    def test_same_spec_same_bytes(self):
        building = load_spec(EXAMPLE)
        first = Path(tempfile.mkdtemp()) / "a.glb"
        second = Path(tempfile.mkdtemp()) / "b.glb"
        Builder(building).export(first.parent, "a")
        Builder(load_spec(EXAMPLE)).export(second.parent, "b")
        self.assertEqual(
            hashlib.sha256(first.read_bytes()).hexdigest(),
            hashlib.sha256(second.read_bytes()).hexdigest(),
            "building the same spec twice produced different bytes",
        )


if __name__ == "__main__":
    unittest.main()
