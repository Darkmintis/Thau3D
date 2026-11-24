"""Deep furniture audit: run the builder in-process and compare every placed
piece against the room it belongs to."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from thau3d.build import Builder  # noqa: E402
from thau3d.spec import load_spec  # noqa: E402

spec_path = sys.argv[1] if len(sys.argv) > 1 else "examples/housewalk/house.thau.json"
building = load_spec(spec_path)
builder = Builder(building)
builder.build()

spaces = {space.id: space for storey in building.storeys for space in storey.spaces}
print(f"{'space':16}{'type':10}{'pieces':>7}  out of room")
problems = 0
for space_id, rects in sorted(builder.furniture_zones.items()):
    space = spaces.get(space_id)
    if space is None:
        continue
    outside = []
    for rect in rects:
        if (
            rect[0] < space.x0 - 0.06
            or rect[1] < space.y0 - 0.06
            or rect[2] > space.x1 + 0.06
            or rect[3] > space.y1 + 0.06
        ):
            outside.append(tuple(round(v, 2) for v in rect))
    problems += len(outside)
    print(f"{space_id:16}{space.type:10}{len(rects):7}  {outside}")

empty = [
    space.id
    for storey in building.storeys
    for space in storey.spaces
    if space.type not in ("stair", "store", "hall", "landing") and not builder.furniture_zones.get(space.id)
]
print("\nrooms with no furniture:", empty or "none")
print("pieces outside their room:", problems)
