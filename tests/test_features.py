"""Feature coverage: balconies, roof forms, straight stairs and dimensional checks."""

import json
import struct
import tempfile
import unittest
from pathlib import Path

from thau3d.build import Builder
from thau3d.geometry import wedge
from thau3d.spec import SpecError, load_spec, validate
from thau3d.verify import verify

ROOT = Path(__file__).resolve().parent.parent
HOUSE = ROOT / "examples" / "housewalk" / "house.thau.json"
CABIN = ROOT / "examples" / "hill-cabin" / "hill.thau.json"


def build(spec_path: Path) -> tuple[dict, dict]:
    directory = Path(tempfile.mkdtemp())
    report = Builder(load_spec(spec_path)).export(directory, "test")
    data = report.glb.read_bytes()
    json_length, _kind = struct.unpack("<II", data[12:20])
    gltf = json.loads(data[20 : 20 + json_length].decode("utf-8"))
    manifest = json.loads(report.manifest.read_text(encoding="utf-8"))
    return gltf, manifest


class WedgeTest(unittest.TestCase):
    def test_has_six_faces_and_a_slope(self):
        mesh = wedge(0, 4, 0, 6, 3.0, 3.0, 4.5, "y0")
        self.assertEqual(len(mesh.positions), 24)
        self.assertEqual(len(mesh.indices), 36)
        heights = {round(point[1], 3) for point in mesh.positions}
        self.assertEqual(heights, {3.0, 4.5})

    def test_high_side_flips_the_slope(self):
        up = wedge(0, 4, 0, 6, 0.0, 0.0, 2.0, "y0")
        down = wedge(0, 4, 0, 6, 0.0, 0.0, 2.0, "y1")
        up_front = max(point[1] for point in up.positions if abs(point[2] - 0.0) < 1e-6)
        down_front = max(point[1] for point in down.positions if abs(point[2] - 0.0) < 1e-6)
        self.assertGreater(up_front, down_front)


class BalconyTest(unittest.TestCase):
    def test_example_builds_two_balconies(self):
        _gltf, manifest = build(HOUSE)
        balconies = manifest["balconies"]
        self.assertEqual(len(balconies), 2)
        for balcony in balconies:
            x0, _y0, x1, _y1 = balcony["rect"]
            self.assertGreater(x1 - x0, 1.0)
            self.assertGreater(balcony["railing"], 0.9)
        # a front balcony must project past y = 0 in plan, i.e. to positive z in glTF
        self.assertTrue(any(entry["rect"][1] < 0 for entry in balconies))

    def test_balcony_produces_a_walkable_support(self):
        _gltf, manifest = build(HOUSE)
        supports = [entry for entry in manifest["supports"] if entry["tag"] == "balcony"]
        self.assertEqual(len(supports), 2)

    def test_balcony_past_the_elevation_is_an_error(self):
        raw = json.loads(HOUSE.read_text(encoding="utf-8"))
        raw["balconies"][0]["span"] = [20, 40]
        path = Path(tempfile.mkdtemp()) / "bad.thau.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(SpecError) as caught:
            load_spec(path)
        self.assertIn("runs past the front elevation", str(caught.exception))


class RoofTest(unittest.TestCase):
    def test_gable_rises_above_the_walls(self):
        gltf, manifest = build(CABIN)
        names = [node.get("name", "") for node in gltf["nodes"]]
        self.assertTrue(any("roof_gable" in name for name in names), "no gable geometry emitted")

        tops = []
        for node in gltf["nodes"]:
            if "roof_gable" not in node.get("name", ""):
                continue
            mesh = gltf["meshes"][node["mesh"]]
            accessor = gltf["accessors"][mesh["primitives"][0]["attributes"]["POSITION"]]
            tops.append(accessor["max"][1])
        wall_top = manifest["storeys"][-1]["top"]
        self.assertGreater(max(tops), wall_top + 0.5)

    def test_terrace_roof_still_gets_a_parapet(self):
        gltf, manifest = build(HOUSE)
        names = [node.get("name", "") for node in gltf["nodes"]]
        self.assertTrue(any("parapet" in name for name in names))
        self.assertFalse(any("roof_gable" in name for name in names))


class StairFormTest(unittest.TestCase):
    def test_straight_stair_reaches_the_next_storey(self):
        # Build a small building whose stair is explicitly straight: the example
        # cabins use the U form, and this test is about the other builder path.
        raw = json.loads(CABIN.read_text(encoding="utf-8"))
        raw["stairs"] = [
            {
                "id": "main",
                "storey": "ground",
                "form": "straight",
                "x": [12.3, 19.7],
                "y": [12, 25.8],
                "width": 3.6,
            }
        ]
        path = Path(tempfile.mkdtemp()) / "straight.thau.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        _gltf, manifest = build(path)
        stair = manifest["stairs"][0]
        self.assertIsNone(stair["landing"])
        storey = manifest["storeys"][0]
        self.assertAlmostEqual(stair["top"], storey["base"] + storey["height"], places=3)
        self.assertGreater(len(stair["steps"]), 10)
        rise = stair["steps"][1]["top"] - stair["steps"][0]["top"]
        self.assertLess(rise, 0.19)


class VerifyTest(unittest.TestCase):
    def test_examples_pass(self):
        for path in (HOUSE, CABIN):
            checks = verify(load_spec(path))
            failures = [check for check in checks if check.level == "fail"]
            self.assertEqual(failures, [], f"{path.name}: {failures}")

    def test_tiny_room_fails(self):
        raw = json.loads(CABIN.read_text(encoding="utf-8"))
        raw["storeys"][1]["spaces"][0]["x"] = [0, 6]
        raw["storeys"][1]["spaces"][0]["y"] = [0, 10]
        path = Path(tempfile.mkdtemp()) / "small.thau.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        checks = verify(load_spec(path))
        self.assertTrue(any(check.level == "fail" and check.name == "room sizes" for check in checks))

    def test_low_ceiling_fails(self):
        raw = json.loads(CABIN.read_text(encoding="utf-8"))
        raw["defaults"]["clearHeight"] = 7.0
        path = Path(tempfile.mkdtemp()) / "low.thau.json"
        path.write_text(json.dumps(raw), encoding="utf-8")
        checks = verify(load_spec(path))
        names = {check.name: check.level for check in checks}
        self.assertEqual(names.get("ceiling height"), "fail")


if __name__ == "__main__":
    unittest.main()
