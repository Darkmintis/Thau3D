"""Spec parsing and validation: the agent's compiler errors."""

import json
import tempfile
import unittest
from pathlib import Path

from thau3d.spec import SpecError, load_spec, validate

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "housewalk" / "house.thau.json"


def write_spec(data: dict) -> Path:
    directory = tempfile.mkdtemp()
    path = Path(directory) / "test.thau.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def base_spec(**overrides) -> dict:
    spec = {
        "version": "0.1",
        "name": "Test",
        "units": "m",
        "footprint": {"width": 10, "depth": 12},
        "storeys": [
            {
                "id": "ground",
                "spaces": [
                    {"id": "living", "type": "living", "x": [0, 10], "y": [0, 6]},
                    {"id": "dining", "type": "dining", "x": [0, 10], "y": [6, 12]},
                ],
            }
        ],
        "stairs": [],
        "windows": [],
        "doors": [],
        "roof": {"parapet": 1.0},
        "site": {},
        "materials": {},
    }
    spec.update(overrides)
    return spec


class ExampleSpecTest(unittest.TestCase):
    def test_example_loads_and_validates(self):
        building = load_spec(EXAMPLE)
        self.assertEqual(len(building.storeys), 3)
        self.assertEqual(sum(len(storey.spaces) for storey in building.storeys), 20)
        self.assertGreater(building.width, 7.0)
        errors = [issue for issue in validate(building) if issue.level == "error"]
        self.assertEqual(errors, [])

    def test_units_are_converted_to_metres(self):
        building = load_spec(EXAMPLE)
        # 26 ft footprint
        self.assertAlmostEqual(building.width, 26 * 0.3048, places=4)


class ValidationTest(unittest.TestCase):
    def test_overlapping_rooms_are_an_error(self):
        spec = base_spec()
        spec["storeys"][0]["spaces"][1]["y"] = [4, 12]
        with self.assertRaises(SpecError) as caught:
            load_spec(write_spec(spec))
        self.assertIn("overlap", str(caught.exception))

    def test_room_outside_footprint_is_an_error(self):
        spec = base_spec()
        spec["storeys"][0]["spaces"][1]["y"] = [6, 20]
        with self.assertRaises(SpecError) as caught:
            load_spec(write_spec(spec))
        self.assertIn("outside the footprint", str(caught.exception))

    def test_stair_outside_its_space_is_an_error(self):
        spec = base_spec(stairs=[{"id": "s", "storey": "ground", "x": [20, 24], "y": [1, 8]}])
        with self.assertRaises(SpecError) as caught:
            load_spec(write_spec(spec))
        self.assertIn("not contained", str(caught.exception))

    def test_unknown_space_type_is_a_warning(self):
        spec = base_spec()
        spec["storeys"][0]["spaces"][0]["type"] = "lving"
        building = load_spec(write_spec(spec))
        messages = [issue.message for issue in validate(building) if issue.level == "warning"]
        self.assertTrue(any("lving" in message for message in messages))
        self.assertTrue(any("living" in message for message in messages), "should suggest a close match")

    def test_bad_units_rejected(self):
        with self.assertRaises(SpecError):
            load_spec(write_spec(base_spec(units="furlong")))

    def test_bad_json_reports_position(self):
        directory = tempfile.mkdtemp()
        path = Path(directory) / "broken.thau.json"
        path.write_text('{"version": "0.1",,}', encoding="utf-8")
        with self.assertRaises(SpecError) as caught:
            load_spec(path)
        self.assertIn("not valid JSON", str(caught.exception))

    def test_unreachable_storey_warns(self):
        spec = base_spec()
        spec["storeys"].append(
            {"id": "first", "spaces": [{"id": "bed", "type": "bedroom", "x": [0, 10], "y": [0, 12]}]}
        )
        building = load_spec(write_spec(spec))
        messages = [issue.message for issue in validate(building) if issue.level == "warning"]
        self.assertTrue(any("no stair" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
