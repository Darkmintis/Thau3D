"""Audit what furniture actually landed in each room of the built model."""

import json
import sys
from pathlib import Path

stem = sys.argv[1] if len(sys.argv) > 1 else "house"
path = Path("viewer/public/models") / f"{stem}.manifest.json"
manifest = json.loads(path.read_text(encoding="utf-8"))
storeys = {s["id"]: s for s in manifest["storeys"]}
spaces = manifest["spaces"]


def space_for(box):
    cx = (box["min"][0] + box["max"][0]) / 2
    cy = -(box["min"][2] + box["max"][2]) / 2
    bottom = box["min"][1]
    for space in spaces:
        base = storeys[space["storey"]]["base"]
        if not (base - 0.05 <= bottom <= base + 0.6):
            continue
        x0, y0, x1, y1 = space["rect"]
        if x0 - 0.05 <= cx <= x1 + 0.05 and y0 - 0.05 <= cy <= y1 + 0.05:
            return space["id"]
    return "UNASSIGNED"


counts = {}
sizes = {}
for box in manifest["colliders"]:
    if box["tag"] != "furniture":
        continue
    space_id = space_for(box)
    counts[space_id] = counts.get(space_id, 0) + 1
    width = box["max"][0] - box["min"][0]
    depth = box["max"][2] - box["min"][2]
    sizes.setdefault(space_id, 0.0)
    sizes[space_id] += width * depth

print(f"{'storey':8}{'space':16}{'type':10}{'area':>8}{'pieces':>8}{'footprint':>11}")
for space in spaces:
    if space["type"] in ("stair", "store"):
        continue
    sid = space["id"]
    print(
        f"{space['storey']:8}{sid:16}{space['type']:10}{space['area']:8.1f}"
        f"{counts.get(sid, 0):8}{sizes.get(sid, 0.0):11.2f}"
    )
print("UNASSIGNED", counts.get("UNASSIGNED", 0))
